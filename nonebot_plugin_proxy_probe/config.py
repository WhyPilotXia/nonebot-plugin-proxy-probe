from __future__ import annotations

from nonebot import get_plugin_config
from pydantic import BaseModel, Field


class PluginConfig(BaseModel):
    proxy_probe_local_ip: str = ""
    proxy_probe_target_ip: str = ""
    proxy_probe_prefix_length: int = 20
    proxy_probe_ports: list[int] = Field(default_factory=lambda: [7897])
    proxy_probe_connect_timeout: float = 0.35
    proxy_probe_proxy_timeout: float = 5.0
    proxy_probe_geo_timeout: float = 5.0
    proxy_probe_workers: int = 256
    proxy_probe_proxy_workers: int = 256
    proxy_probe_geo_workers: int = 256
    proxy_probe_bind_source_ip: bool = True
    proxy_probe_test_urls: list[str] = Field(
        default_factory=lambda: [
            "https://api.ip.sb/ip",
            "https://cp.cloudflare.com/generate_204",
            "https://www.gstatic.com/generate_204",
        ]
    )
    proxy_probe_exclude_ips: list[str] = Field(default_factory=list)


plugin_config = get_plugin_config(PluginConfig)
