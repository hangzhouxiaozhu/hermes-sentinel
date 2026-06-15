"""
Publish Archiver — 文章发布归档器

记录已发布文章的标题、摘要和发布日期，支持按日期范围查询。
所有数据存储在 ~/.hermes/logs/publish_archive.jsonl。
"""

import json
import os
from datetime import date, datetime
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
ARCHIVE_FILE = HERMES_HOME / "logs" / "publish_archive.jsonl"


# ── 写入 ──────────────────────────────────────────────────

def record(title: str, digest: str = "", platform: str = "wechat",
           article_id: str = "", url: str = "") -> dict:
    """
    记录一篇已发布的文章。

    参数:
        title: 文章标题
        digest: 文章摘要（可选）
        platform: 发布平台（默认 wechat）
        article_id: 平台文章 ID（可选）
        url: 文章链接（可选）

    返回:
        {"recorded": True, "date": str, "title": str}
    """
    ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    entry = {
        "date": today,
        "timestamp": datetime.now().isoformat(),
        "title": title,
        "digest": digest,
        "platform": platform,
        "article_id": article_id,
        "url": url,
    }

    with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"recorded": True, "date": today, "title": title}


# ── 查询 ──────────────────────────────────────────────────

def get_by_date(target_date: str) -> list[dict]:
    """
    查询指定日期的所有文章。

    参数:
        target_date: 日期字符串 "YYYY-MM-DD"

    返回:
        [{...}, ...] 按时间排序的文章列表
    """
    if not ARCHIVE_FILE.exists():
        return []

    results = []
    with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("date") == target_date:
                    results.append(entry)
            except json.JSONDecodeError:
                continue

    return sorted(results, key=lambda e: e.get("timestamp", ""))


def get_by_date_range(start_date: str, end_date: str) -> list[dict]:
    """
    查询日期范围内的所有文章。

    参数:
        start_date: 起始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"

    返回:
        [{...}, ...] 按日期排序的文章列表
    """
    if not ARCHIVE_FILE.exists():
        return []

    results = []
    with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                d = entry.get("date", "")
                if start_date <= d <= end_date:
                    results.append(entry)
            except json.JSONDecodeError:
                continue

    return sorted(results, key=lambda e: e.get("date", ""))


def list_all() -> list[dict]:
    """
    列出所有已归档文章，按日期倒序。

    返回:
        [{...}, ...]
    """
    if not ARCHIVE_FILE.exists():
        return []

    results = []
    with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return sorted(results, key=lambda e: e.get("date", ""), reverse=True)


def get_stats() -> dict:
    """
    获取发布统计。

    返回:
        {"total": int, "first_date": str, "last_date": str, "by_platform": {...}}
    """
    all_articles = list_all()
    if not all_articles:
        return {"total": 0, "first_date": None, "last_date": None, "by_platform": {}}

    by_platform = {}
    for a in all_articles:
        p = a.get("platform", "unknown")
        by_platform[p] = by_platform.get(p, 0) + 1

    return {
        "total": len(all_articles),
        "first_date": all_articles[-1]["date"],
        "last_date": all_articles[0]["date"],
        "by_platform": by_platform,
    }


def get_latest(n: int = 5) -> list[dict]:
    """
    获取最近 n 篇文章。

    返回:
        [{...}, ...]
    """
    return list_all()[:n]
