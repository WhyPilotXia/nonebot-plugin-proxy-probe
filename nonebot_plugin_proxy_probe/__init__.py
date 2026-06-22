"""NoneBot 代理扫描与缓存插件。"""

from nonebot import require
from nonebot.plugin import PluginMetadata

require("nonebot_plugin_localstore")

from .config import PluginConfig  # noqa: E402

__plugin_meta__ = PluginMetadata(
    name="代理扫描",
    description="扫描并缓存 Clash HTTP 代理、出口 IP 与属地",
    usage=(
        "/proxy 显示缓存结果\n"
        "/proxy -h 或 --help 显示帮助\n"
        "/proxy -i <IPv4> 或 --ip <IPv4> 设置目标参考 IP\n"
        "/proxy -p 或 --probe 重新扫描\n"
        "/proxy -r 或 --refresh 刷新缓存\n"
        "/proxy -s 或 --stop 停止后台任务"
    ),
    type="application",
    supported_adapters={"~onebot.v11"},
    config=PluginConfig,
)

from . import commands as commands  # noqa: E402,F401
