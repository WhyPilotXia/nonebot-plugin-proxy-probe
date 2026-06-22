from __future__ import annotations

import ipaddress
import json
import platform
import queue
import random
import re
import socket
import struct
import subprocess
import threading
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import requests
import urllib3
from requests.adapters import HTTPAdapter

from .models import (
    NOT_PROBED,
    UNAVAILABLE,
    PipelineProgress,
    ProxyRecord,
)


STOP = object()
UpdateCallback = Callable[
    [PipelineProgress, list[ProxyRecord], int, int], None
]
RefreshCallback = Callable[[list[ProxyRecord], int, int], None]


class SourceAddressAdapter(HTTPAdapter):
    """让直连及代理连接均从指定本机 IP 发出。"""

    def __init__(self, source_ip: str, *args: Any, **kwargs: Any) -> None:
        self.source_ip = source_ip
        super().__init__(*args, **kwargs)

    def init_poolmanager(
        self,
        connections: int,
        maxsize: int,
        block: bool = False,
        **pool_kwargs: Any,
    ) -> None:
        pool_kwargs["source_address"] = (self.source_ip, 0)
        super().init_poolmanager(
            connections, maxsize, block=block, **pool_kwargs
        )

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        proxy_kwargs["source_address"] = (self.source_ip, 0)
        return super().proxy_manager_for(proxy, **proxy_kwargs)


@dataclass(frozen=True)
class ProbeConfig:
    local_ip: str
    target_ip: str
    prefix_length: int
    proxy_ports: tuple[int, ...]
    connect_timeout: float
    proxy_timeout: float
    geo_timeout: float
    workers: int
    proxy_workers: int
    geo_workers: int
    bind_source_ip: bool
    proxy_test_urls: tuple[str, ...]
    exclude_ips: tuple[str, ...]

    def validate(self) -> None:
        ipaddress.IPv4Address(self.local_ip)
        ipaddress.IPv4Address(self.target_ip)
        if not 0 <= self.prefix_length <= 32:
            raise ValueError("prefix_length 必须在 0 到 32 之间")
        if not self.proxy_ports:
            raise ValueError("proxy_ports 不能为空")
        if len(set(self.proxy_ports)) != len(self.proxy_ports):
            raise ValueError("proxy_ports 不能包含重复端口")
        for port in self.proxy_ports:
            if not 1 <= port <= 65535:
                raise ValueError("代理端口必须在 1 到 65535 之间")
        if min(self.connect_timeout, self.proxy_timeout, self.geo_timeout) <= 0:
            raise ValueError("超时时间必须大于 0")
        for name, count, maximum in (
            ("workers", self.workers, 1024),
            ("proxy_workers", self.proxy_workers, 512),
            ("geo_workers", self.geo_workers, 512),
        ):
            if not 1 <= count <= maximum:
                raise ValueError(f"{name} 必须在 1 到 {maximum} 之间")
        if not self.proxy_test_urls:
            raise ValueError("proxy_test_urls 不能为空")
        for url in self.proxy_test_urls:
            if urlsplit(url).scheme != "https":
                raise ValueError("代理验证地址必须使用 https://")
        for item in self.exclude_ips:
            ipaddress.IPv4Address(item)


@dataclass(frozen=True)
class ProbeRunResult:
    progress: PipelineProgress
    results: list[ProxyRecord]
    interrupted: bool


@dataclass(frozen=True)
class RefreshRunResult:
    results: list[ProxyRecord]
    completed: int
    total: int
    interrupted: bool


def source_address(config: ProbeConfig) -> tuple[str, int] | None:
    return (config.local_ip, 0) if config.bind_source_ip else None


@dataclass(frozen=True)
class LocalNetwork:
    local_ip: str
    dns_servers: tuple[str, ...] = ()
    interface_name: str = ""


_VIRTUAL_INTERFACE_WORDS = (
    "meta",
    "tailscale",
    "zerotier",
    "tunnel",
    "virtual",
    "hyper-v",
    "vmware",
    "virtualbox",
    "loopback",
    "docker",
    "veth",
    "virbr",
    "wsl",
    "wireguard",
)


def _valid_local_ipv4(value: str) -> str | None:
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return None
    if address.is_loopback or address.is_link_local or address.is_unspecified:
        return None
    return str(address)


def _read_resolv_conf() -> list[str]:
    result: list[str] = []
    try:
        lines = Path("/etc/resolv.conf").read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return result
    for line in lines:
        fields = line.split()
        if len(fields) < 2 or fields[0].lower() != "nameserver":
            continue
        try:
            server = str(ipaddress.IPv4Address(fields[1]))
        except ValueError:
            continue
        if server not in result:
            result.append(server)
    return result


def _windows_network_candidates() -> list[dict[str, Any]]:
    script = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Get-NetIPConfiguration |
    Where-Object { $_.IPv4Address -and $_.IPv4DefaultGateway } |
    ForEach-Object {
        $adapter = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
        $route = Get-NetRoute -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue |
            Sort-Object RouteMetric, InterfaceMetric |
            Select-Object -First 1
        $routeMetric = if ($route) { [int]$route.RouteMetric } else { 999999 }
        $interfaceMetric = if ($route) { [int]$route.InterfaceMetric } else { 999999 }
        [PSCustomObject]@{
            ip = [string](@($_.IPv4Address)[0].IPAddress)
            alias = [string]$_.InterfaceAlias
            description = [string]$_.InterfaceDescription
            virtual = [bool]$adapter.Virtual
            status = [string]$adapter.Status
            route_metric = $routeMetric
            interface_metric = $interfaceMetric
            gateway = [string]$_.IPv4DefaultGateway.NextHop
            dns_servers = @($_.DNSServer.ServerAddresses | Where-Object { $_ -match '^\d+\.' })
        }
    } |
    ConvertTo-Json -Depth 4 -Compress
"""
    try:
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
            ],
            check=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = completed.stdout.lstrip("\ufeff").strip()
        if not text:
            return []
        raw = json.loads(text)
    except (
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ):
        return []
    rows = raw if isinstance(raw, list) else [raw]
    return [row for row in rows if isinstance(row, dict)]


def _linux_interface_ipv4(interface: str) -> str | None:
    try:
        import fcntl
    except ImportError:
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        request = struct.pack(
            "256s",
            interface[:15].encode("utf-8"),
        )
        response = fcntl.ioctl(sock.fileno(), 0x8915, request)
        return _valid_local_ipv4(socket.inet_ntoa(response[20:24]))
    except OSError:
        return None
    finally:
        sock.close()


def _linux_network_candidates() -> list[dict[str, Any]]:
    try:
        lines = Path("/proc/net/route").read_text(
            encoding="ascii",
            errors="replace",
        ).splitlines()[1:]
    except OSError:
        return []
    dns_servers = _read_resolv_conf()
    rows: list[dict[str, Any]] = []
    for line in lines:
        fields = line.split()
        if len(fields) < 8 or fields[1] != "00000000":
            continue
        try:
            flags = int(fields[3], 16)
            metric = int(fields[6])
            gateway = socket.inet_ntoa(
                struct.pack("<L", int(fields[2], 16))
            )
        except (ValueError, OSError, struct.error):
            continue
        if not flags & 0x1:
            continue
        interface = fields[0]
        local_ip = _linux_interface_ipv4(interface)
        if not local_ip:
            continue
        rows.append(
            {
                "ip": local_ip,
                "alias": interface,
                "description": interface,
                "virtual": False,
                "status": "Up",
                "route_metric": metric,
                "interface_metric": 0,
                "gateway": gateway,
                "dns_servers": dns_servers,
            }
        )
    return rows


def _fallback_network() -> LocalNetwork:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        local_ip = _valid_local_ipv4(str(sock.getsockname()[0]))
        if not local_ip:
            raise ValueError
    except (OSError, ValueError) as exc:
        raise ValueError("无法自动获取当前出站网卡 IPv4") from exc
    finally:
        sock.close()
    return LocalNetwork(
        local_ip=local_ip,
        dns_servers=tuple(_read_resolv_conf()),
    )


def detect_local_network(preferred_ip: str = "") -> LocalNetwork:
    """跨平台选择有默认网关的实体 IPv4 网卡。"""
    system = platform.system()
    if system == "Windows":
        candidates = _windows_network_candidates()
    elif system == "Linux":
        candidates = _linux_network_candidates()
    else:
        candidates = []

    normalized_preferred = (
        _valid_local_ipv4(preferred_ip) if preferred_ip else None
    )
    if preferred_ip and not normalized_preferred:
        raise ValueError(f"配置的 local_ip 不是有效 IPv4：{preferred_ip}")

    prepared: list[tuple[int, bool, dict[str, Any]]] = []
    for row in candidates:
        local_ip = _valid_local_ipv4(str(row.get("ip") or ""))
        if not local_ip:
            continue
        name = " ".join(
            (
                str(row.get("alias") or ""),
                str(row.get("description") or ""),
            )
        ).lower()
        is_virtual = bool(row.get("virtual")) or any(
            word in name for word in _VIRTUAL_INTERFACE_WORDS
        )
        if str(row.get("status") or "").lower() not in ("", "up"):
            continue
        try:
            score = int(row.get("route_metric", 999999)) + int(
                row.get("interface_metric", 999999)
            )
        except (TypeError, ValueError):
            score = 999999
        prepared.append((score, is_virtual, {**row, "ip": local_ip}))

    selected: dict[str, Any] | None = None
    if normalized_preferred:
        for _, _, row in prepared:
            if row["ip"] == normalized_preferred:
                selected = row
                break
        if selected is None:
            return LocalNetwork(
                local_ip=normalized_preferred,
                dns_servers=tuple(_read_resolv_conf()),
            )
    elif prepared:
        physical = [item for item in prepared if not item[1]]
        pool = physical or prepared
        selected = min(pool, key=lambda item: item[0])[2]

    if selected is None:
        return _fallback_network()

    dns_servers: list[str] = []
    raw_dns = selected.get("dns_servers") or []
    if isinstance(raw_dns, str):
        raw_dns = [raw_dns]
    for value in [*raw_dns, selected.get("gateway")]:
        try:
            server = str(ipaddress.IPv4Address(str(value or "")))
        except ValueError:
            continue
        if server not in dns_servers:
            dns_servers.append(server)
    return LocalNetwork(
        local_ip=str(selected["ip"]),
        dns_servers=tuple(dns_servers),
        interface_name=str(selected.get("alias") or ""),
    )


def detect_local_ip() -> str:
    return detect_local_network().local_ip


def _skip_dns_name(data: bytes, offset: int) -> int:
    while offset < len(data):
        length = data[offset]
        if length & 0xC0 == 0xC0:
            return offset + 2
        offset += 1
        if length == 0:
            return offset
        offset += length
    raise ValueError("DNS 响应中的名称格式错误")


def _resolve_a_via_server(
    hostname: str,
    server: str,
    local_ip: str,
    timeout: float,
) -> list[str]:
    transaction_id = random.randint(0, 65535)
    labels = hostname.rstrip(".").split(".")
    question = b"".join(
        bytes((len(label.encode("idna")),)) + label.encode("idna")
        for label in labels
    ) + b"\x00"
    packet = (
        struct.pack("!HHHHHH", transaction_id, 0x0100, 1, 0, 0, 0)
        + question
        + struct.pack("!HH", 1, 1)
    )
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(min(timeout, 3.0))
        if not ipaddress.IPv4Address(server).is_loopback:
            sock.bind((local_ip, 0))
        sock.sendto(packet, (server, 53))
        data, _ = sock.recvfrom(4096)
    finally:
        sock.close()
    if len(data) < 12:
        return []
    response_id, flags, qd_count, answer_count, _, _ = struct.unpack(
        "!HHHHHH",
        data[:12],
    )
    if response_id != transaction_id or flags & 0x000F:
        return []
    offset = 12
    for _ in range(qd_count):
        offset = _skip_dns_name(data, offset) + 4
    result: list[str] = []
    for _ in range(answer_count):
        offset = _skip_dns_name(data, offset)
        if offset + 10 > len(data):
            break
        record_type, record_class, _, data_length = struct.unpack(
            "!HHIH",
            data[offset : offset + 10],
        )
        offset += 10
        record_data = data[offset : offset + data_length]
        offset += data_length
        if record_type == 1 and record_class == 1 and data_length == 4:
            address = socket.inet_ntoa(record_data)
            if address not in result:
                result.append(address)
    return result


def _resolve_direct_ipv4(
    hostname: str,
    dns_servers: tuple[str, ...],
    local_ip: str,
    timeout: float,
) -> list[str]:
    for server in dns_servers:
        try:
            addresses = _resolve_a_via_server(
                hostname,
                server,
                local_ip,
                timeout,
            )
        except OSError:
            continue
        if addresses:
            return addresses
    if not dns_servers:
        try:
            return list(
                dict.fromkeys(
                    socket.gethostbyname_ex(hostname)[2]
                )
            )
        except OSError:
            pass
    return []


def _direct_https_get(
    hostname: str,
    path: str,
    local_ip: str,
    dns_servers: tuple[str, ...],
    timeout: float,
) -> bytes:
    addresses = _resolve_direct_ipv4(
        hostname,
        dns_servers,
        local_ip,
        timeout,
    )
    last_error: Exception | None = None
    for address in addresses:
        pool = urllib3.HTTPSConnectionPool(
            address,
            port=443,
            server_hostname=hostname,
            assert_hostname=hostname,
            source_address=(local_ip, 0),
            timeout=urllib3.Timeout(connect=timeout, read=timeout),
            retries=False,
        )
        try:
            response = pool.request(
                "GET",
                path,
                headers={
                    "Host": hostname,
                    "User-Agent": "nonebot-plugin-proxy-probe/0.1",
                },
                redirect=False,
            )
            if 200 <= response.status < 400:
                return bytes(response.data)
        except Exception as exc:
            last_error = exc
        finally:
            pool.close()
    if last_error:
        raise last_error
    raise OSError(f"无法直连解析或访问 {hostname}")


def detect_direct_public_ip(
    local_ip: str,
    timeout: float,
    bind_source_ip: bool = True,
    dns_servers: tuple[str, ...] = (),
) -> str:
    """绕过环境代理和透明代理 DNS，取得实体网卡出口 IPv4。"""
    def normalize(value: Any) -> str | None:
        text = str(value or "").strip()
        try:
            address = ipaddress.IPv4Address(text)
        except ValueError:
            return None
        return str(address) if address.is_global else None

    if bind_source_ip:
        try:
            payload = _direct_https_get(
                "api.myip.la",
                "/cn?json",
                local_ip,
                dns_servers,
                timeout=timeout,
            )
            result = normalize(
                json.loads(payload.decode("utf-8")).get("ip")
            )
            if result:
                return result
        except (OSError, ValueError, TypeError, AttributeError, urllib3.HTTPError):
            pass

        try:
            payload = _direct_https_get(
                "api.ip.sb",
                "/ip",
                local_ip,
                dns_servers,
                timeout=timeout,
            )
            result = normalize(payload.decode("utf-8", errors="replace"))
            if result:
                return result
        except (OSError, urllib3.HTTPError):
            pass

    if bind_source_ip and dns_servers:
        raise ValueError("无法通过实体网卡直连接口获取当前出口 IPv4")

    session = requests.Session()
    session.trust_env = False
    session.headers["User-Agent"] = "nonebot-plugin-proxy-probe/0.1"
    if bind_source_ip:
        adapter: HTTPAdapter = SourceAddressAdapter(
            local_ip,
            max_retries=0,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
    try:
        try:
            response = session.get(
                "https://api.ip.sb/ip",
                timeout=timeout,
            )
            response.raise_for_status()
            result = normalize(response.text)
            if result:
                return result
        except requests.RequestException:
            pass
    finally:
        session.close()
    raise ValueError("无法通过直连回退接口获取当前出口 IPv4")


def check_source_binding(config: ProbeConfig) -> None:
    config.validate()
    if not config.bind_source_ip:
        return
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((config.local_ip, 0))
    except OSError as exc:
        raise ValueError(
            f"无法绑定本机 IP {config.local_ip}，请检查插件配置"
        ) from exc
    finally:
        sock.close()


def make_proxy_session(
    ip: str,
    port: int,
    config: ProbeConfig,
) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    adapter: HTTPAdapter
    if config.bind_source_ip:
        adapter = SourceAddressAdapter(config.local_ip, max_retries=0)
    else:
        adapter = HTTPAdapter(max_retries=0)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    proxy_url = f"http://{ip}:{port}"
    session.proxies = {"http": proxy_url, "https": proxy_url}
    session.headers["User-Agent"] = "nonebot-plugin-proxy-probe/0.1"
    return session


def is_port_open(ip: str, port: int, config: ProbeConfig) -> bool:
    try:
        with socket.create_connection(
            (ip, port),
            timeout=config.connect_timeout,
            source_address=source_address(config),
        ):
            return True
    except OSError:
        return False


def verify_proxy(
    ip: str,
    port: int,
    config: ProbeConfig,
    stop_event: threading.Event,
) -> str | None:
    session = make_proxy_session(ip, port, config)
    try:
        for url in config.proxy_test_urls:
            if stop_event.is_set():
                return None
            try:
                response = session.get(
                    url,
                    timeout=config.proxy_timeout,
                    allow_redirects=False,
                )
                if 200 <= response.status_code < 500:
                    host = urlsplit(url).hostname or url
                    return f"{host} HTTP {response.status_code}"
            except requests.RequestException:
                continue
    finally:
        session.close()
    return None


def join_location(*parts: Any) -> str:
    values: list[str] = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in values:
            values.append(text)
    return " / ".join(values) or "未知属地"


def parse_myip_la(data: dict[str, Any]) -> tuple[str, str]:
    location = data.get("location") or {}
    return (
        str(data.get("ip") or "").strip(),
        join_location(
            location.get("country_name"),
            location.get("province"),
            location.get("city"),
        ),
    )


def parse_ip_sb(data: dict[str, Any]) -> tuple[str, str]:
    return (
        str(data.get("ip") or "").strip(),
        join_location(
            data.get("country"),
            data.get("region"),
            data.get("city"),
        ),
    )


def probe_proxy_location(
    ip: str,
    port: int,
    config: ProbeConfig,
    stop_event: threading.Event,
) -> tuple[str, str]:
    session = make_proxy_session(ip, port, config)
    json_apis: tuple[
        tuple[str, Callable[[dict[str, Any]], tuple[str, str]]], ...
    ] = (
        ("https://api.myip.la/cn?json", parse_myip_la),
        ("https://api.ip.sb/geoip", parse_ip_sb),
    )
    try:
        for url, parser in json_apis:
            if stop_event.is_set():
                return NOT_PROBED, NOT_PROBED
            try:
                response = session.get(url, timeout=config.geo_timeout)
                response.raise_for_status()
                public_ip, location = parser(response.json())
                if public_ip:
                    return public_ip, location
            except (
                requests.RequestException,
                ValueError,
                TypeError,
                KeyError,
                AttributeError,
            ):
                continue

        if stop_event.is_set():
            return NOT_PROBED, NOT_PROBED
        try:
            response = session.get(
                "https://myip.ipip.net",
                timeout=config.geo_timeout,
            )
            response.raise_for_status()
            response.encoding = "utf-8"
            match = re.search(
                r"当前\s*IP\s*[：:]\s*(\S+)\s+来自于\s*[：:]\s*(.+)",
                response.text.strip(),
            )
            if match:
                return (
                    match.group(1).strip(),
                    match.group(2).strip() or "未知属地",
                )
        except requests.RequestException:
            pass
    finally:
        session.close()
    return UNAVAILABLE, UNAVAILABLE


def _sorted_records(
    records: dict[tuple[str, int], ProxyRecord],
    port_order: dict[int, int],
) -> list[ProxyRecord]:
    return sorted(
        records.values(),
        key=lambda item: (
            ipaddress.IPv4Address(item.ip),
            port_order.get(item.port, 999999),
        ),
    )


def run_probe(
    config: ProbeConfig,
    stop_event: threading.Event,
    callback: UpdateCallback | None = None,
) -> ProbeRunResult:
    check_source_binding(config)
    network = ipaddress.ip_network(
        f"{config.target_ip}/{config.prefix_length}",
        strict=False,
    )
    targets = [str(ip) for ip in network]
    total = len(targets)
    excluded = {str(ipaddress.IPv4Address(ip)) for ip in config.exclude_ips}
    port_order = {port: index for index, port in enumerate(config.proxy_ports)}

    scan_queue: queue.Queue[Any] = queue.Queue()
    proxy_queue: queue.Queue[Any] = queue.Queue()
    geo_queue: queue.Queue[Any] = queue.Queue()
    state_lock = threading.RLock()
    results: dict[tuple[str, int], ProxyRecord] = {}
    ip_states: dict[str, dict[str, Any]] = {}
    counters = {"scan": 0, "proxy": 0, "geo": 0}
    notify_counter = {"scan": 0}

    def snapshot(task_current: int | None = None) -> None:
        if callback is None:
            return
        with state_lock:
            progress = PipelineProgress(
                total=total,
                scan_completed=counters["scan"],
                proxy_completed=counters["proxy"],
                geo_completed=counters["geo"],
            )
            records = _sorted_records(results, port_order)
        callback(
            progress,
            records,
            progress.scan_completed if task_current is None else task_current,
            total,
        )

    def complete_proxy_endpoint(
        ip: str,
        verified: ProxyRecord | None,
    ) -> None:
        queue_geo: ProxyRecord | None = None
        with state_lock:
            state = ip_states[ip]
            if verified is not None:
                results[(verified.ip, verified.port)] = verified
                state["geo_remaining"] += 1
                queue_geo = verified
            state["proxy_remaining"] -= 1
            if state["proxy_remaining"] == 0:
                counters["proxy"] += 1
                state["proxy_counted"] = True
                if state["geo_remaining"] == 0:
                    counters["geo"] += 1
                    state["geo_counted"] = True
        if queue_geo is not None and not stop_event.is_set():
            geo_queue.put(queue_geo)
        snapshot()

    def scan_worker() -> None:
        while True:
            item = scan_queue.get()
            try:
                if item is STOP:
                    return
                ip = str(item)
                if stop_event.is_set():
                    continue
                opened: list[int] = []
                if ip not in excluded:
                    for port in config.proxy_ports:
                        if stop_event.is_set():
                            break
                        if is_port_open(ip, port, config):
                            opened.append(port)
                if stop_event.is_set():
                    continue

                with state_lock:
                    counters["scan"] += 1
                    ip_states[ip] = {
                        "proxy_remaining": len(opened),
                        "geo_remaining": 0,
                        "proxy_counted": not opened,
                        "geo_counted": not opened,
                    }
                    if not opened:
                        counters["proxy"] += 1
                        counters["geo"] += 1
                    notify_counter["scan"] += 1
                    should_notify = (
                        notify_counter["scan"] >= 64
                        or counters["scan"] == total
                    )
                    if should_notify:
                        notify_counter["scan"] = 0
                for port in opened:
                    proxy_queue.put((ip, port))
                if should_notify or opened:
                    snapshot()
            finally:
                scan_queue.task_done()

    def proxy_worker() -> None:
        while True:
            item = proxy_queue.get()
            try:
                if item is STOP:
                    return
                if stop_event.is_set():
                    continue
                ip, port = item
                status = verify_proxy(ip, port, config, stop_event)
                if stop_event.is_set():
                    continue
                record = None
                if status:
                    record = ProxyRecord(
                        ip=ip,
                        port=port,
                        proxy_status=status,
                        public_ip=NOT_PROBED,
                        location=NOT_PROBED,
                    )
                complete_proxy_endpoint(ip, record)
            finally:
                proxy_queue.task_done()

    def geo_worker() -> None:
        while True:
            item = geo_queue.get()
            try:
                if item is STOP:
                    return
                if stop_event.is_set():
                    continue
                proxy: ProxyRecord = item
                public_ip, location = probe_proxy_location(
                    proxy.ip,
                    proxy.port,
                    config,
                    stop_event,
                )
                if stop_event.is_set():
                    continue
                updated = ProxyRecord(
                    ip=proxy.ip,
                    port=proxy.port,
                    proxy_status=proxy.proxy_status,
                    public_ip=public_ip,
                    location=location,
                )
                with state_lock:
                    results[(proxy.ip, proxy.port)] = updated
                    state = ip_states[proxy.ip]
                    state["geo_remaining"] -= 1
                    if (
                        state["proxy_counted"]
                        and state["geo_remaining"] == 0
                        and not state["geo_counted"]
                    ):
                        counters["geo"] += 1
                        state["geo_counted"] = True
                snapshot()
            finally:
                geo_queue.task_done()

    def start_workers(
        count: int,
        target: Callable[[], None],
        name: str,
    ) -> list[threading.Thread]:
        threads = [
            threading.Thread(
                target=target,
                name=f"proxy-probe-{name}-{index + 1}",
                daemon=True,
            )
            for index in range(count)
        ]
        for thread in threads:
            thread.start()
        return threads

    geo_threads = start_workers(config.geo_workers, geo_worker, "geo")
    proxy_threads = start_workers(
        config.proxy_workers, proxy_worker, "verify"
    )
    scan_threads = start_workers(config.workers, scan_worker, "scan")

    for target in targets:
        scan_queue.put(target)
    for _ in scan_threads:
        scan_queue.put(STOP)
    for thread in scan_threads:
        thread.join()

    for _ in proxy_threads:
        proxy_queue.put(STOP)
    for thread in proxy_threads:
        thread.join()

    for _ in geo_threads:
        geo_queue.put(STOP)
    for thread in geo_threads:
        thread.join()

    snapshot()
    with state_lock:
        final_progress = PipelineProgress(
            total=total,
            scan_completed=counters["scan"],
            proxy_completed=counters["proxy"],
            geo_completed=counters["geo"],
        )
        final_results = _sorted_records(results, port_order)
    return ProbeRunResult(
        progress=final_progress,
        results=final_results,
        interrupted=stop_event.is_set(),
    )


def run_refresh(
    config: ProbeConfig,
    cached_results: list[ProxyRecord],
    stop_event: threading.Event,
    callback: RefreshCallback | None = None,
) -> RefreshRunResult:
    check_source_binding(config)
    total = len(cached_results)
    port_order = {port: index for index, port in enumerate(config.proxy_ports)}
    results = {
        (item.ip, item.port): item
        for item in cached_results
    }
    verify_queue: queue.Queue[Any] = queue.Queue()
    geo_queue: queue.Queue[Any] = queue.Queue()
    lock = threading.RLock()
    completed = 0

    def snapshot() -> None:
        if callback is None:
            return
        with lock:
            records = _sorted_records(results, port_order)
            current = completed
        callback(records, current, total)

    def verify_worker() -> None:
        nonlocal completed
        while True:
            item = verify_queue.get()
            try:
                if item is STOP:
                    return
                if stop_event.is_set():
                    continue
                proxy: ProxyRecord = item
                status = verify_proxy(
                    proxy.ip,
                    proxy.port,
                    config,
                    stop_event,
                )
                if stop_event.is_set():
                    continue
                key = (proxy.ip, proxy.port)
                if not status:
                    with lock:
                        results.pop(key, None)
                        completed += 1
                    snapshot()
                    continue
                verified = ProxyRecord(
                    ip=proxy.ip,
                    port=proxy.port,
                    proxy_status=status,
                    public_ip=NOT_PROBED,
                    location=NOT_PROBED,
                )
                with lock:
                    results[key] = verified
                geo_queue.put(verified)
                snapshot()
            finally:
                verify_queue.task_done()

    def geo_worker() -> None:
        nonlocal completed
        while True:
            item = geo_queue.get()
            try:
                if item is STOP:
                    return
                if stop_event.is_set():
                    continue
                proxy: ProxyRecord = item
                public_ip, location = probe_proxy_location(
                    proxy.ip,
                    proxy.port,
                    config,
                    stop_event,
                )
                if stop_event.is_set():
                    continue
                updated = ProxyRecord(
                    ip=proxy.ip,
                    port=proxy.port,
                    proxy_status=proxy.proxy_status,
                    public_ip=public_ip,
                    location=location,
                )
                with lock:
                    results[(proxy.ip, proxy.port)] = updated
                    completed += 1
                snapshot()
            finally:
                geo_queue.task_done()

    def start_workers(
        count: int,
        target: Callable[[], None],
        name: str,
    ) -> list[threading.Thread]:
        threads = [
            threading.Thread(
                target=target,
                name=f"proxy-refresh-{name}-{index + 1}",
                daemon=True,
            )
            for index in range(count)
        ]
        for thread in threads:
            thread.start()
        return threads

    geo_threads = start_workers(config.geo_workers, geo_worker, "geo")
    verify_threads = start_workers(
        config.proxy_workers, verify_worker, "verify"
    )
    for record in cached_results:
        verify_queue.put(record)
    for _ in verify_threads:
        verify_queue.put(STOP)
    for thread in verify_threads:
        thread.join()

    for _ in geo_threads:
        geo_queue.put(STOP)
    for thread in geo_threads:
        thread.join()

    snapshot()
    with lock:
        final_results = _sorted_records(results, port_order)
        final_completed = completed
    return RefreshRunResult(
        results=final_results,
        completed=final_completed,
        total=total,
        interrupted=stop_event.is_set(),
    )
