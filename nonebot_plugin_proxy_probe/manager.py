from __future__ import annotations

import asyncio
import copy
import threading
import time
from datetime import datetime

from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    MessageEvent,
    MessageSegment,
)
from nonebot.log import logger

from .cache import load_cache, load_target_ip, save_cache, save_target_ip
from .config import PluginConfig, plugin_config
from .models import CacheState, PipelineProgress, ProxyRecord
from .probe import (
    ProbeConfig,
    ProbeRunResult,
    RefreshProgress,
    RefreshRunResult,
    detect_direct_public_ip,
    detect_local_network,
    run_probe,
    run_refresh,
)
from .render import image_to_base64, render_cache_image


def format_time() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def build_probe_config(
    config: PluginConfig,
    persisted_target_ip: str = "",
) -> ProbeConfig:
    network = detect_local_network(config.proxy_probe_local_ip.strip())
    local_ip = network.local_ip
    target_ip = (
        persisted_target_ip.strip()
        or config.proxy_probe_target_ip.strip()
    )
    if not target_ip:
        target_ip = detect_direct_public_ip(
            local_ip,
            config.proxy_probe_geo_timeout,
            config.proxy_probe_bind_source_ip,
            network.dns_servers,
        )
    logger.info(
        f"代理扫描使用网卡 {network.interface_name or '自动路由'} "
        f"({local_ip})，目标参考 IP {target_ip}"
    )
    return ProbeConfig(
        local_ip=local_ip,
        target_ip=target_ip,
        prefix_length=config.proxy_probe_prefix_length,
        proxy_ports=tuple(config.proxy_probe_ports),
        connect_timeout=config.proxy_probe_connect_timeout,
        proxy_timeout=config.proxy_probe_proxy_timeout,
        geo_timeout=config.proxy_probe_geo_timeout,
        workers=config.proxy_probe_workers,
        proxy_workers=config.proxy_probe_proxy_workers,
        geo_workers=config.proxy_probe_geo_workers,
        bind_source_ip=config.proxy_probe_bind_source_ip,
        proxy_test_urls=tuple(config.proxy_probe_test_urls),
        exclude_ips=tuple(config.proxy_probe_exclude_ips),
    )


class ProbeManager:
    def __init__(self) -> None:
        self._state_lock = threading.RLock()
        self._state = load_cache()
        self._persisted_target_ip = load_target_ip()
        self._task_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._stop_event: threading.Event | None = None
        self._recipient: tuple[Bot, MessageEvent] | None = None
        self._last_save = 0.0
        self._persist_lock = threading.RLock()
        environment_target_ip = plugin_config.proxy_probe_target_ip.strip()
        if self._persisted_target_ip and environment_target_ip:
            logger.warning(
                "proxy_probe_target_ip 环境变量与 LocalStore 持久化设置"
                "同时存在，将使用 LocalStore 缓存值 "
                f"{self._persisted_target_ip}，忽略环境变量值 "
                f"{environment_target_ip}"
            )
        if self._state.running:
            self._state.running = False
            self._state.task_status = "任务因 Bot 重启而中止"
            save_cache(self._state)

    def get_state(self) -> CacheState:
        with self._state_lock:
            return copy.deepcopy(self._state)

    def get_image_segment(self) -> MessageSegment:
        image = render_cache_image(self.get_state())
        return MessageSegment.image(image_to_base64(image))

    def running_description(self) -> str:
        state = self.get_state()
        names = {"probe": "重新扫描", "refresh": "缓存刷新"}
        return names.get(state.operation, "后台")

    def configured_target_ip(self) -> str:
        return (
            self._persisted_target_ip
            or plugin_config.proxy_probe_target_ip.strip()
        )

    async def set_target_ip(self, target_ip: str) -> tuple[bool, str]:
        async with self._task_lock:
            if self._task is not None and not self._task.done():
                return (
                    False,
                    f"已有{self.running_description()}任务正在运行，"
                    "请先使用 /proxy -s 停止。",
                )
            try:
                await asyncio.to_thread(save_target_ip, target_ip)
            except (OSError, ValueError) as exc:
                return False, f"保存目标 IP 失败：{exc}"
            self._persisted_target_ip = target_ip
            return (
                True,
                f"目标参考 IP 已持久化为 {target_ip}，"
                "后续扫描和刷新将优先使用该值。",
            )

    def _persist(self, force: bool = False) -> None:
        with self._persist_lock:
            now = time.monotonic()
            if not force and now - self._last_save < 0.5:
                return
            with self._state_lock:
                snapshot = copy.deepcopy(self._state)
            try:
                save_cache(snapshot)
                self._last_save = now
            except OSError as exc:
                logger.warning(f"保存代理缓存失败: {exc}")

    def _probe_callback(
        self,
        progress: PipelineProgress,
        results: list[ProxyRecord],
        current: int,
        total: int,
    ) -> None:
        with self._state_lock:
            self._state.progress = progress
            self._state.results = list(results)
            self._state.task_current = current
            self._state.task_total = total
        self._persist()

    def _refresh_callback(
        self,
        results: list[ProxyRecord],
        refresh: RefreshProgress,
    ) -> None:
        with self._state_lock:
            self._state.results = list(results)
            current = self._state.progress
            self._state.progress = PipelineProgress(
                total=current.total,
                scan_completed=current.scan_completed,
                open_count=current.open_count,
                proxy_tested=refresh.proxy_tested,
                proxy_count=refresh.proxy_count,
                geo_tested=refresh.geo_tested,
                geo_success=refresh.geo_success,
            )
            self._state.task_current = refresh.completed
            self._state.task_total = refresh.total
        self._persist()

    async def start(
        self,
        operation: str,
        bot: Bot,
        event: MessageEvent,
    ) -> tuple[bool, str]:
        async with self._task_lock:
            if self._task is not None and not self._task.done():
                return (
                    False,
                    f"已有{self.running_description()}任务正在运行，"
                    "可使用 /proxy -s 停止。",
                )
            if operation == "refresh" and not self.get_state().results:
                return False, "当前没有缓存代理，请先使用 /proxy -p 扫描。"

            self._stop_event = threading.Event()
            self._recipient = (bot, event)
            with self._state_lock:
                self._state.running = True
                self._state.operation = operation
                self._state.task_status = "运行中"
                self._state.task_current = 0
                if operation == "probe":
                    total = 1 << (32 - plugin_config.proxy_probe_prefix_length)
                    self._state.task_total = total
                    self._state.progress = PipelineProgress(total=total)
                    self._state.results = []
                else:
                    self._state.task_total = len(self._state.results)
                    current = self._state.progress
                    self._state.progress = PipelineProgress(
                        total=current.total,
                        scan_completed=current.scan_completed,
                        open_count=current.open_count,
                    )
            self._persist(force=True)
            self._task = asyncio.create_task(
                self._run(operation),
                name=f"nonebot-proxy-{operation}",
            )
            return True, ""

    async def stop(
        self,
        bot: Bot,
        event: MessageEvent,
    ) -> tuple[bool, str]:
        async with self._task_lock:
            task = self._task
            stop_event = self._stop_event
            if task is None or task.done() or stop_event is None:
                return False, "当前没有正在运行的代理任务。"
            self._recipient = (bot, event)
            with self._state_lock:
                self._state.task_status = "正在停止"
            self._persist(force=True)
            stop_event.set()
        await asyncio.shield(task)
        return True, ""

    async def _run(self, operation: str) -> None:
        stopped = False
        error: Exception | None = None
        origin_recipient = self._recipient
        persisted_target_ip = self._persisted_target_ip
        target_ip_auto_detected = not (
            persisted_target_ip
            or plugin_config.proxy_probe_target_ip.strip()
        )
        try:
            config = await asyncio.to_thread(
                build_probe_config,
                plugin_config,
                persisted_target_ip,
            )
            with self._state_lock:
                self._state.local_ip = config.local_ip
                self._state.target_ip = config.target_ip
            self._persist(force=True)
            if (
                target_ip_auto_detected
                and origin_recipient is not None
            ):
                bot, event = origin_recipient
                if isinstance(event, GroupMessageEvent):
                    try:
                        await bot.call_api(
                            "set_msg_emoji_like",
                            group_id=event.group_id,
                            message_id=event.message_id,
                            emoji_id="4",
                            set=True,
                        )
                    except Exception as exc:
                        logger.warning(f"设置 IP 探测成功表情失败: {exc}")
            stop_event = self._stop_event
            if stop_event is None:
                raise RuntimeError("停止事件未初始化")
            if operation == "probe":
                result: ProbeRunResult = await asyncio.to_thread(
                    run_probe,
                    config,
                    stop_event,
                    self._probe_callback,
                )
                stopped = result.interrupted
                with self._state_lock:
                    self._state.progress = result.progress
                    self._state.results = result.results
                    self._state.task_current = result.progress.scan_completed
                    self._state.task_total = result.progress.total
                    completed_at = format_time()
                    self._state.scan_time = completed_at
                    self._state.refresh_time = completed_at
            else:
                cached = self.get_state().results
                refresh_result: RefreshRunResult = await asyncio.to_thread(
                    run_refresh,
                    config,
                    cached,
                    stop_event,
                    self._refresh_callback,
                )
                stopped = refresh_result.interrupted
                with self._state_lock:
                    self._state.results = refresh_result.results
                    refresh = refresh_result.progress
                    current = self._state.progress
                    self._state.progress = PipelineProgress(
                        total=current.total,
                        scan_completed=current.scan_completed,
                        open_count=current.open_count,
                        proxy_tested=refresh.proxy_tested,
                        proxy_count=refresh.proxy_count,
                        geo_tested=refresh.geo_tested,
                        geo_success=refresh.geo_success,
                    )
                    self._state.task_current = refresh.completed
                    self._state.task_total = refresh.total
                    self._state.refresh_time = format_time()
        except Exception as exc:
            error = exc
            logger.exception("代理探测后台任务失败")
        finally:
            with self._state_lock:
                self._state.running = False
                if error is not None:
                    self._state.task_status = f"失败：{error}"
                elif stopped:
                    self._state.task_status = "已停止，显示部分结果"
                else:
                    self._state.task_status = "已完成"
                snapshot = copy.deepcopy(self._state)
            try:
                save_cache(snapshot)
            except OSError as exc:
                logger.warning(f"保存代理最终缓存失败: {exc}")

            recipient = self._recipient
            if recipient is not None:
                bot, event = recipient
                try:
                    if error is not None:
                        await bot.send(event, f"代理任务失败：{error}")
                    await bot.send(event, self.get_image_segment())
                except Exception:
                    logger.exception("发送代理结果图片失败")

            async with self._task_lock:
                self._task = None
                self._stop_event = None
                self._recipient = None


manager = ProbeManager()
