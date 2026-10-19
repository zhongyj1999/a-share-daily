"""A-share daily report health check.

Checks whether today's report has been generated and whether key data sources
are healthy.  Returns a non-zero exit code when something is wrong.

Usage:
    python scripts/health_check.py
    python scripts/health_check.py --fix          # rerun daily_report.py if needed
    python scripts/health_check.py --strict       # also fail on weekends/holidays
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE_DIR / "reports"
SNAPSHOT_DIR = BASE_DIR / "data" / "snapshots"
ALERT_FILE = BASE_DIR / "data" / "health_alert.json"

TZ = ZoneInfo("Asia/Shanghai")


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


# Sources considered critical for the report to be trustworthy.
CRITICAL_SOURCES = ("index", "xq", "industry", "limit_up", "ths_hot")


def now_cn() -> datetime:
    return datetime.now(tz=TZ)


def last_trading_day(ref: datetime | None = None) -> datetime:
    """Return the most recent trading day (Mon-Fri) before or on ref."""
    ref = ref or now_cn()
    date = ref.date()
    while date.weekday() >= 5:  # Saturday=5, Sunday=6
        date -= timedelta(days=1)
    return datetime.combine(date, datetime.min.time(), tzinfo=TZ)


def file_mtime(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=TZ)


def run_daily_report() -> int:
    cmd = [sys.executable, str(BASE_DIR / "scripts" / "daily_report.py")]
    print(f"正在重跑报告：{' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=BASE_DIR, check=False)
    return result.returncode


def check_sources(snapshot: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    sources = {s["key"]: s for s in snapshot.get("sources") or []}
    for key in CRITICAL_SOURCES:
        src = sources.get(key)
        if not src:
            warnings.append(f"关键数据源缺失：{key}")
            continue
        if src.get("status") != "ok":
            warnings.append(f"关键数据源异常：{src.get('label', key)} -> {src.get('status')}（{src.get('detail', '')}）")
    return warnings


def save_alert(status: str, messages: list[str]) -> None:
    ALERT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ALERT_FILE.write_text(
        json.dumps(
            {
                "checked_at": now_cn().isoformat(timespec="seconds"),
                "status": status,
                "messages": messages,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="A 股每日报告健康检查")
    parser.add_argument("--fix", action="store_true", help="发现异常时自动重跑 daily_report.py")
    parser.add_argument("--strict", action="store_true", help="非交易日也要求当天有报告")
    args = parser.parse_args()

    today = now_cn().date()
    today_str = today.strftime("%Y-%m-%d")
    latest_html = REPORT_DIR / "latest.html"
    snapshot_path = SNAPSHOT_DIR / f"{today_str}.json"

    messages: list[str] = []
    status = "ok"

    # Determine whether we expect a run today.
    is_weekday = today.weekday() < 5
    expect_run_today = args.strict or is_weekday

    # Check latest.html exists and was updated today (if a run was expected).
    if expect_run_today:
        mtime = file_mtime(latest_html)
        if mtime is None:
            messages.append(f"{today_str} 未生成 reports/latest.html")
            status = "fail"
        elif mtime.date() != today:
            messages.append(
                f"reports/latest.html 不是今天更新：文件日期 {mtime.date()}，今天 {today}"
            )
            status = "fail"

    # Check today's snapshot exists.
    if expect_run_today and not snapshot_path.exists():
        messages.append(f"{today_str} 的快照文件不存在：{snapshot_path}")
        status = "fail"

    # Parse snapshot for source-level warnings.
    if snapshot_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            source_warnings = check_sources(snapshot)
            if source_warnings:
                messages.extend(source_warnings)
                status = "warn" if status == "ok" else status
            global_warnings = snapshot.get("warnings") or []
            if global_warnings:
                messages.append(f"采集过程中产生 {len(global_warnings)} 条警告，详见报告数据源面板")
                status = "warn" if status == "ok" else status
        except Exception:  # noqa: BLE001
            messages.append(f"解析快照失败：{snapshot_path}")
            status = "fail"

    if not expect_run_today:
        messages.append("今日为非工作日，不强制要求生成报告（--strict 可关闭此豁免）")

    # Auto-fix: rerun the report once if we detected a missing/outdated report.
    if args.fix and status == "fail":
        try:
            rc = run_daily_report()
            if rc == 0:
                print("重跑成功，重新检查...", flush=True)
                return main()
            messages.append(f"自动重跑 daily_report.py 失败，返回码 {rc}")
        except Exception:  # noqa: BLE001
            messages.append("自动重跑 daily_report.py 时发生异常")
            traceback.print_exc()
        status = "fail"

    save_alert(status, messages)

    print(f"健康检查：{status}")
    for msg in messages:
        print(f"  - {msg}")

    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
