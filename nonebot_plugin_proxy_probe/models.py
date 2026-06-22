from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


UNAVAILABLE = "无法探测代理后地址"
NOT_PROBED = "未探测代理后地址"


@dataclass(frozen=True)
class ProxyRecord:
    ip: str
    port: int
    proxy_status: str = ""
    public_ip: str = NOT_PROBED
    location: str = NOT_PROBED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProxyRecord":
        return cls(
            ip=str(data.get("ip", "")),
            port=int(data.get("port", 0)),
            proxy_status=str(data.get("proxy_status", "")),
            public_ip=str(data.get("public_ip", NOT_PROBED)),
            location=str(data.get("location", NOT_PROBED)),
        )


@dataclass(frozen=True)
class PipelineProgress:
    total: int = 0
    scan_completed: int = 0
    proxy_completed: int = 0
    geo_completed: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineProgress":
        return cls(
            total=max(0, int(data.get("total", 0))),
            scan_completed=max(0, int(data.get("scan_completed", 0))),
            proxy_completed=max(0, int(data.get("proxy_completed", 0))),
            geo_completed=max(0, int(data.get("geo_completed", 0))),
        )


@dataclass
class CacheState:
    scan_time: str = "未扫描"
    refresh_time: str = "未刷新"
    local_ip: str = "未获取"
    target_ip: str = "未获取"
    running: bool = False
    operation: str = ""
    task_status: str = "空闲"
    task_current: int = 0
    task_total: int = 0
    progress: PipelineProgress = field(default_factory=PipelineProgress)
    results: list[ProxyRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "scan_time": self.scan_time,
            "refresh_time": self.refresh_time,
            "local_ip": self.local_ip,
            "target_ip": self.target_ip,
            "running": self.running,
            "operation": self.operation,
            "task_status": self.task_status,
            "task_current": self.task_current,
            "task_total": self.task_total,
            "progress": self.progress.to_dict(),
            "results": [item.to_dict() for item in self.results],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CacheState":
        raw_results = data.get("results") or []
        results: list[ProxyRecord] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            try:
                record = ProxyRecord.from_dict(item)
            except (TypeError, ValueError):
                continue
            if record.ip and 1 <= record.port <= 65535:
                results.append(record)

        progress_data = data.get("progress")
        if not isinstance(progress_data, dict):
            progress_data = {}
        return cls(
            scan_time=str(data.get("scan_time", "未扫描")),
            refresh_time=str(data.get("refresh_time", "未刷新")),
            local_ip=str(data.get("local_ip", "未获取")),
            target_ip=str(data.get("target_ip", "未获取")),
            running=bool(data.get("running", False)),
            operation=str(data.get("operation", "")),
            task_status=str(data.get("task_status", "空闲")),
            task_current=max(0, int(data.get("task_current", 0))),
            task_total=max(0, int(data.get("task_total", 0))),
            progress=PipelineProgress.from_dict(progress_data),
            results=results,
        )
