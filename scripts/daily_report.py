"""A-share daily report entry point.

Usage:
    python scripts/daily_report.py
    python scripts/daily_report.py --quiet
    python scripts/daily_report.py --tag close
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import render  # noqa: E402
from sources import BASE_DIR, REPORT_DIR, SNAPSHOT_DIR, collect_all  # noqa: E402


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="生成 A 股每日行情报告")
    parser.add_argument("--quiet", action="store_true", help="只输出最终结果")
    parser.add_argument("--tag", default="", help="文件名后缀，例如 close")
    args = parser.parse_args()

    def log(message: str) -> None:
        if not args.quiet:
            print(message, flush=True)

    started = time.time()
    log("=" * 68)
    log("A股每日行情报告 · 数据采集中")
    log("=" * 68)

    try:
        data = collect_all(log=log)
    except Exception:  # noqa: BLE001
        print("数据采集失败：", file=sys.stderr)
        traceback.print_exc()
        return 1

    if not data.get("indexes") and not data.get("stocks"):
        print("数据采集结果为空，已终止，不生成空白报告。", file=sys.stderr)
        return 2

    data_date = str(data.get("data_date") or data.get("generated_date") or "unknown")
    suffix = f"-{args.tag.strip()}" if args.tag.strip() else ""
    html_name = f"{data_date}{suffix}.html"
    md_name = f"{data_date}{suffix}.md"
    json_name = f"{data_date}{suffix}.json"

    try:
        html_text = render.render_html(data)
        markdown_text = render.render_markdown(data)
        snapshot_text = render.dump_snapshot(data)
    except Exception:  # noqa: BLE001
        print("报告渲染失败：", file=sys.stderr)
        traceback.print_exc()
        return 3

    html_path = REPORT_DIR / html_name
    md_path = REPORT_DIR / md_name
    latest_html = REPORT_DIR / f"latest{suffix}.html"
    latest_md = REPORT_DIR / f"latest{suffix}.md"
    snapshot_path = SNAPSHOT_DIR / json_name

    write_text(html_path, html_text)
    write_text(md_path, markdown_text)
    write_text(latest_html, html_text)
    write_text(latest_md, markdown_text)
    write_text(snapshot_path, snapshot_text)

    market = data.get("market") or {}
    elapsed = time.time() - started
    print("")
    print("报告生成完成")
    print(f"  数据日期   {data_date}  ({data.get('session_status', '')})")
    print(f"  统计个股   {int(market.get('stock_count', 0)):,}")
    print(f"  涨停个股   {int(market.get('limit_up_count', 0))}")
    print(f"  跨平台热榜 {sum(len(rows) for rows in (data.get('hot_lists') or {}).values())} 条")
    print(f"  HTML       {html_path}")
    print(f"  Markdown   {md_path}")
    print(f"  快照       {snapshot_path}")
    print(f"  最新副本   {latest_html}")
    print(f"  耗时       {elapsed:.1f}s")
    warnings = data.get("warnings") or []
    if warnings:
        print(f"  数据提示   {len(warnings)} 条（详见报告数据源面板）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
