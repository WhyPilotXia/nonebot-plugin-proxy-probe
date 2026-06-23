from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import yaml

from .cache import DATA_DIR
from .models import ProxyRecord
from .render import sorted_results


def _proxy_names(records: list[ProxyRecord]) -> list[str]:
    locations = [
        str(record.location or "").strip() or "未知属地"
        for record in records
    ]
    totals = Counter(locations)
    used: defaultdict[str, int] = defaultdict(int)
    names: list[str] = []
    for location in locations:
        used[location] += 1
        if totals[location] == 1:
            names.append(location)
        else:
            names.append(f"{location} #{used[location]}")
    return names


def _is_singapore(location: str) -> bool:
    normalized = str(location or "").strip().casefold()
    return "新加坡" in normalized or "singapore" in normalized


def export_clash_yaml(
    results: list[ProxyRecord],
    now: datetime | None = None,
) -> tuple[Path, int, int]:
    records = sorted_results(results)
    if not records:
        raise ValueError("当前没有缓存代理，请先使用 /proxy -p 扫描。")

    names = _proxy_names(records)
    proxies = [
        {
            "name": name,
            "type": "http",
            "server": record.ip,
            "port": record.port,
        }
        for name, record in zip(names, records, strict=True)
    ]
    singapore_names = [
        name
        for name, record in zip(names, records, strict=True)
        if _is_singapore(record.location)
    ]
    auto_names = singapore_names or names

    document = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "proxies": proxies,
        "proxy-groups": [
            {
                "name": "自动选择",
                "type": "url-test",
                "proxies": auto_names,
                "url": "https://www.gstatic.com/generate_204",
                "interval": 300,
                "tolerance": 20,
            },
            {
                "name": "节点选择",
                "type": "select",
                "proxies": ["自动选择", *names],
            },
        ],
        "rules": ["MATCH,节点选择"],
    }

    exported_at = now or datetime.now().astimezone()
    filename = (
        f"{len(records)}个-"
        f"{exported_at:%m月%d日%H时%M分}.yaml"
    )
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    path.write_text(
        yaml.safe_dump(
            document,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )
    return path, len(records), len(singapore_names)
