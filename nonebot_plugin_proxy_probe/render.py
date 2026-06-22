from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import CacheState, ProxyRecord


FONT_PATH = Path(__file__).resolve().parent / "assets" / "原神字体.ttf"
MAX_DISPLAY_RESULTS = 50
IMAGE_WIDTH = 1900
MARGIN = 42
ROW_HEIGHT = 58
COL_WIDTHS = (380, 180, 380, 876)
COL_HEADERS = ("IP", "端口", "代理后 IP", "代理后属地")


def get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_PATH), size=size)
    except OSError:
        return ImageFont.load_default()


def fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> str:
    text = str(text)
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    suffix = "…"
    left, right = 0, len(text)
    while left < right:
        middle = (left + right + 1) // 2
        candidate = text[:middle] + suffix
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            left = middle
        else:
            right = middle - 1
    return text[:left] + suffix


def sorted_results(results: list[ProxyRecord]) -> list[ProxyRecord]:
    def ip_key(item: ProxyRecord) -> tuple[int, int]:
        parts = item.ip.split(".")
        numeric = 0
        if len(parts) == 4 and all(part.isdigit() for part in parts):
            for part in parts:
                numeric = numeric * 256 + int(part)
        return numeric, item.port

    return sorted(results, key=ip_key)


def render_cache_image(state: CacheState) -> bytes:
    visible = sorted_results(state.results)[:MAX_DISPLAY_RESULTS]
    rows = max(1, len(visible))
    header_height = 380
    image_height = header_height + ROW_HEIGHT * (rows + 1) + MARGIN
    image = Image.new("RGB", (IMAGE_WIDTH, image_height), "#f3f6fb")
    draw = ImageDraw.Draw(image)

    title_font = get_font(38)
    info_font = get_font(25)
    table_header_font = get_font(27)
    table_font = get_font(25)

    draw.text(
        (MARGIN, 28),
        "Clash 代理扫描结果",
        font=title_font,
        fill="#172033",
    )
    count_text = f"共 {len(state.results)} 条"
    if len(state.results) > MAX_DISPLAY_RESULTS:
        count_text += f"（仅显示前 {MAX_DISPLAY_RESULTS} 条）"
    draw.text(
        (MARGIN, 92),
        f"扫描时间：{state.scan_time}    刷新时间：{state.refresh_time}    {count_text}",
        font=info_font,
        fill="#344054",
    )

    operation_names = {"probe": "重新扫描", "refresh": "缓存刷新"}
    operation = operation_names.get(state.operation, "无")
    task_line = f"当前任务：{operation} / {state.task_status}"
    if state.task_total:
        task_line += f" / {state.task_current}/{state.task_total}"
    draw.text(
        (MARGIN, 140),
        f"本机出站 IP：{state.local_ip}    目标参考 IP：{state.target_ip}",
        font=info_font,
        fill="#344054",
    )

    draw.text(
        (MARGIN, 188),
        task_line,
        font=info_font,
        fill="#175cd3" if state.running else "#475467",
    )

    progress = state.progress
    draw.text(
        (MARGIN, 236),
        f"端口扫描：{progress.open_count} open in {progress.scan_completed}",
        font=info_font,
        fill="#344054",
    )
    draw.text(
        (MARGIN + 540, 236),
        f"代理验证：{progress.proxy_count} proxy in {progress.proxy_tested}",
        font=info_font,
        fill="#344054",
    )
    draw.text(
        (MARGIN + 1080, 236),
        f"属地探测：{progress.geo_success} tested in {progress.geo_tested}",
        font=info_font,
        fill="#344054",
    )

    table_left = MARGIN
    table_top = 305
    table_right = IMAGE_WIDTH - MARGIN
    x_positions = [table_left]
    for width in COL_WIDTHS:
        x_positions.append(x_positions[-1] + width)
    x_positions[-1] = table_right

    draw.rounded_rectangle(
        (
            table_left,
            table_top,
            table_right,
            table_top + ROW_HEIGHT * (rows + 1),
        ),
        radius=12,
        fill="white",
        outline="#cfd8e6",
        width=2,
    )
    draw.rectangle(
        (
            table_left,
            table_top,
            table_right,
            table_top + ROW_HEIGHT,
        ),
        fill="#dbeafe",
    )

    for index, header in enumerate(COL_HEADERS):
        left = x_positions[index]
        right = x_positions[index + 1]
        bbox = draw.textbbox((0, 0), header, font=table_header_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        draw.text(
            (
                left + (right - left - text_width) / 2,
                table_top + (ROW_HEIGHT - text_height) / 2 - bbox[1],
            ),
            header,
            font=table_header_font,
            fill="#172033",
        )

    if visible:
        row_values = [
            (item.ip, str(item.port), item.public_ip, item.location)
            for item in visible
        ]
    else:
        row_values = [("暂无缓存代理", "", "", "")]

    for row_index, values in enumerate(row_values, start=1):
        top = table_top + row_index * ROW_HEIGHT
        if row_index % 2 == 0:
            draw.rectangle(
                (table_left, top, table_right, top + ROW_HEIGHT),
                fill="#f8fafc",
            )
        for column_index, value in enumerate(values):
            left = x_positions[column_index]
            right = x_positions[column_index + 1]
            padding = 16
            shown = fit_text(
                draw,
                value,
                table_font,
                right - left - padding * 2,
            )
            bbox = draw.textbbox((0, 0), shown, font=table_font)
            text_height = bbox[3] - bbox[1]
            draw.text(
                (
                    left + padding,
                    top + (ROW_HEIGHT - text_height) / 2 - bbox[1],
                ),
                shown,
                font=table_font,
                fill="#172033",
            )
        draw.line(
            (table_left, top, table_right, top),
            fill="#e4e7ec",
            width=1,
        )

    for x in x_positions[1:-1]:
        draw.line(
            (
                x,
                table_top,
                x,
                table_top + ROW_HEIGHT * (rows + 1),
            ),
            fill="#cfd8e6",
            width=1,
        )

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def image_to_base64(image_bytes: bytes) -> str:
    return "base64://" + base64.b64encode(image_bytes).decode("ascii")
