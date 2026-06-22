from __future__ import annotations

import ipaddress

from nonebot import on_command
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageEvent,
)
from nonebot.log import logger
from nonebot.params import CommandArg

from .manager import manager


USAGE = (
    "用法：\n"
    "/proxy 显示缓存结果\n"
    "/proxy -h 或 --help 显示命令帮助\n"
    "/proxy -i <IPv4> 或 --ip <IPv4> 设置目标参考 IP\n"
    "/proxy -p 或 --probe 重新扫描\n"
    "/proxy -r 或 --refresh 刷新缓存\n"
    "/proxy -s 或 --stop 停止后台任务"
)


def parse_command(argument: str) -> tuple[str, str] | None:
    normalized = " ".join(argument.strip().split())
    actions = {
        "": ("show", ""),
        "-h": ("help", ""),
        "--help": ("help", ""),
        "-p": ("probe", ""),
        "--probe": ("probe", ""),
        "-r": ("refresh", ""),
        "--refresh": ("refresh", ""),
        "-s": ("stop", ""),
        "--stop": ("stop", ""),
    }
    exact = actions.get(normalized)
    if exact is not None:
        return exact

    if normalized.startswith("--ip="):
        return "ip", normalized.partition("=")[2].strip()
    fields = normalized.split(" ", 1)
    if fields[0] in {"-i", "--ip"}:
        return "ip", fields[1].strip() if len(fields) == 2 else ""
    return None


def parse_action(argument: str) -> str | None:
    """保留简单动作解析接口，供旧调用方兼容。"""
    parsed = parse_command(argument)
    return parsed[0] if parsed is not None else None


async def set_emoji(
    bot: Bot,
    event: MessageEvent,
    emoji_id: str,
) -> None:
    if not isinstance(event, GroupMessageEvent):
        return
    try:
        await bot.call_api(
            "set_msg_emoji_like",
            group_id=event.group_id,
            message_id=event.message_id,
            emoji_id=emoji_id,
            set=True,
        )
    except Exception as exc:
        logger.warning(f"设置消息表情失败: {exc}")


proxy_command = on_command("proxy", priority=5, block=True)


@proxy_command.handle()
async def handle_proxy(
    bot: Bot,
    event: MessageEvent,
    args: Message = CommandArg(),
) -> None:
    parsed = parse_command(args.extract_plain_text())
    if parsed is None:
        await proxy_command.finish(USAGE)
    action, value = parsed

    if action == "show":
        await proxy_command.finish(manager.get_image_segment())

    if action == "help":
        await proxy_command.finish(USAGE)

    if action == "ip":
        if not value:
            await proxy_command.finish(
                "请提供目标参考 IPv4，例如："
                "/proxy -i 218.194.50.3"
            )
        try:
            target_ip = str(ipaddress.IPv4Address(value))
        except ValueError:
            await proxy_command.finish(f"不是有效的 IPv4 地址：{value}")
        saved, message = await manager.set_target_ip(target_ip)
        await proxy_command.finish(message)

    if action == "probe":
        await set_emoji(bot, event, "427")
        started, message = await manager.start("probe", bot, event)
        if not started:
            await proxy_command.finish(message)
        return

    if action == "refresh":
        await set_emoji(bot, event, "294")
        started, message = await manager.start("refresh", bot, event)
        if not started:
            await proxy_command.finish(message)
        return

    if action == "stop":
        stopped, message = await manager.stop(bot, event)
        if not stopped:
            await proxy_command.finish(message)
        return
