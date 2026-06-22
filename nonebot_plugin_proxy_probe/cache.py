from __future__ import annotations

import ipaddress
import json
import os
import threading
from pathlib import Path

from nonebot import require

require("nonebot_plugin_localstore")

import nonebot_plugin_localstore as localstore  # noqa: E402

from .models import CacheState  # noqa: E402


DATA_DIR: Path = localstore.get_plugin_data_dir()
CACHE_PATH = DATA_DIR / "proxy_cache.json"
SETTINGS_PATH = DATA_DIR / "settings.json"
_CACHE_LOCK = threading.RLock()


def _write_json(path: Path, data: dict[str, object]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def load_cache() -> CacheState:
    with _CACHE_LOCK:
        try:
            raw = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return CacheState()
        if not isinstance(raw, dict):
            return CacheState()
        try:
            state = CacheState.from_dict(raw)
        except (TypeError, ValueError):
            return CacheState()

        # Bot 重启后不存在可恢复的工作线程，不能继续显示“运行中”。
        if state.running:
            state.running = False
            state.task_status = "任务因 Bot 重启而中止"
        return state


def save_cache(state: CacheState) -> None:
    with _CACHE_LOCK:
        _write_json(CACHE_PATH, state.to_dict())


def load_target_ip() -> str:
    """读取用户通过命令持久化设置的目标参考 IPv4。"""
    with _CACHE_LOCK:
        try:
            raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return ""
    if not isinstance(raw, dict):
        return ""
    value = str(raw.get("target_ip") or "").strip()
    try:
        return str(ipaddress.IPv4Address(value)) if value else ""
    except ValueError:
        return ""


def save_target_ip(target_ip: str) -> None:
    normalized = str(ipaddress.IPv4Address(target_ip))
    with _CACHE_LOCK:
        _write_json(
            SETTINGS_PATH,
            {
                "version": 1,
                "target_ip": normalized,
            },
        )
