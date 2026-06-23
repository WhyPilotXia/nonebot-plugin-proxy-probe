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
        "/proxy -c 或 --cancel 停止后台任务\n"
        "/proxy -s <编号> 或 --set <编号> 设置当前进程代理\n"
        "/proxy -e 或 --export 导出 Clash YAML 并发送群文件"
    ),
    type="application",
    homepage="https://github.com/WhyPilotXia/nonebot-plugin-proxy-probe",
    supported_adapters={"~onebot.v11"},
    config=PluginConfig,
)

from . import commands as commands  # noqa: E402,F401
