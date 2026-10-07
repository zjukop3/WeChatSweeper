"""生成 README 用 SVG 截图（基于真实工具输出）。

用法：
    python scripts/make_screenshots.py

会重建合成微信数据，分别渲染 scan / dry-run / clean 三张 SVG 到 screenshots/。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEMO = Path("/tmp/wxs_demo_ss")
TRASH = Path("/tmp/wxs_trash_ss")
OUT = ROOT / "screenshots"


def run(cmd, env=None):
    subprocess.run(cmd, check=True, env={**os.environ, **(env or {})})


def main() -> int:
    # 清理旧产物
    if DEMO.exists():
        shutil.rmtree(DEMO)
    if TRASH.exists():
        shutil.rmtree(TRASH)
    OUT.mkdir(parents=True, exist_ok=True)

    run([sys.executable, str(ROOT / "scripts/demo_data.py"), str(DEMO)])

    from rich.console import Console

    from wechat_sweeper import ui as U
    from wechat_sweeper.cleaner import CleanOptions, clean_scan
    from wechat_sweeper.detector import detect_accounts
    from wechat_sweeper.scanner import ScanOptions, aggregate, scan_accounts

    accounts = detect_accounts(extra_roots=[DEMO], include_platform_roots=False)
    opts = ScanOptions(categories=tuple(accounts and ["file", "video", "image"]), days=365)
    results = scan_accounts(accounts, opts)
    agg = aggregate(results)

    def rec_console() -> Console:
        return Console(record=True, force_terminal=True, color_system="truecolor",
                       width=96)

    # 1) 扫描仪表盘 + 明细
    c = rec_console()
    U.render_banner(c)
    c.print("[dim]⏳ 正在检测微信/企业微信账号…[/]")
    c.print()
    U.render_dashboard(accounts, agg, results, c)
    c.print()
    U.render_scan_detail(results, c)
    c.save_svg(str(OUT / "scan.svg"), title="WeChatSweeper scan")

    # 2) Dry-Run 预览
    c = rec_console()
    U.render_banner(c)
    U.render_dashboard(accounts, agg, results, c)
    c.print()
    report = clean_scan(results, accounts, CleanOptions(dry_run=True))
    U.render_clean_report(report, c)
    # 明细表
    from wechat_sweeper.cli import _build_outcome_table
    c.print(_build_outcome_table(report))
    c.save_svg(str(OUT / "dry_run.svg"), title="WeChatSweeper dry-run")

    # 3) 清理完成（真实执行，回退到本地托管回收站）
    os.environ["WECHATSWEeper_TRASH_DIR"] = str(TRASH)
    c = rec_console()
    U.render_banner(c)
    U.render_dashboard(accounts, agg, results, c)
    c.print()
    report = clean_scan(results, accounts, CleanOptions(permanent=False, dry_run=False))
    U.render_clean_report(report, c)
    c.save_svg(str(OUT / "clean.svg"), title="WeChatSweeper clean")

    print(f"已生成截图于 {OUT}:")
    for f in sorted(OUT.glob("*.svg")):
        print(f"  {f.name}  ({f.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
