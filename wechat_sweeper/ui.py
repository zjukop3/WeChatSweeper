"""rich 渲染层：仪表盘、扫描结果表、清理进度与汇总。

所有渲染函数接受可选 ``console``，便于测试时捕获输出（截图/校验）。
"""
from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import List, Optional

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)
from rich.table import Table
from rich.text import Text

from wechat_sweeper import __version__
from wechat_sweeper.cleaner import CleanReport
from wechat_sweeper.detector import (
    ALL_CATEGORIES,
    APP_LABELS,
    Account,
    summarize_accounts,
)
from wechat_sweeper.scanner import ScanResult
from wechat_sweeper.utils import humanize_size

# 配色
C_PRIMARY = "bright_cyan"
C_ACCENT = "bright_magenta"
C_OK = "bright_green"
C_WARN = "bright_yellow"
C_DIM = "grey70"

BANNER = r"""
 __        __    _     ___ _   _ _____ ___ ____ ____
 \ \      / /__ | |__ / __| | | | ____/ __|_ _/ ___|
  \ \ /\ / / _ \| '_ \ (__| |_| |  _| \__ \| |\___ \
   \ V  V / (_) | |_) )__) |  _  | |___ ___) | | ___) |
    \_/\_/ \___/|_.__/\____|_| |_|_____|____/___|____/
"""


def new_console(file=None) -> Console:
    return Console(file=file, force_terminal=True, color_system="truecolor", width=92)


def _cat_color(cat: str) -> str:
    return {
        "file": "bright_blue",
        "video": "bright_magenta",
        "image": "bright_green",
        "cache": "bright_yellow",
        "attach": "bright_cyan",
    }.get(cat, "white")


def render_banner(console: Console) -> None:
    console.print(BANNER, style=f"bold {C_PRIMARY}", justify="center")
    console.print(
        f"[bold {C_ACCENT}]WeChatSweeper[/] [dim]v{__version__}  ·  "
        f"跨平台微信/企业微信缓存清理工具[/]",
        justify="center",
    )
    console.print(
        "[dim]🧹 自动检测账号 · 按类型/时间过滤 · 安全移入回收站 · "
        "不触碰文字聊天记录[/]",
        justify="center",
    )


def render_dashboard(
    accounts: List[Account],
    agg: dict,
    results: Optional[List[ScanResult]] = None,
    console: Optional[Console] = None,
) -> None:
    """渲染主页：账号概览 + 体积分布条形图。

    :param results: 若提供，账号表的"占用空间"列显示该账号"待清理"体积
        （与底部总量口径一致）；否则显示账号缓存总占用。
    """
    console = console or new_console()
    summary = summarize_accounts(accounts)

    # 账号 → 待清理体积
    scanned_by_account = {}
    if results:
        for r in results:
            scanned_by_account[str(r.account.base_path.resolve()).lower()] = r.total_size

    # —— 账号列表表 ——
    acct_table = Table(
        title="🔍 已检测到账号",
        box=box.ROUNDED,
        show_lines=False,
        title_style=f"bold {C_PRIMARY}",
        expand=True,
    )
    acct_table.add_column("#", style=C_DIM, width=3)
    acct_table.add_column("应用", style="bold")
    acct_table.add_column("账号 ID", style="white")
    acct_table.add_column("缓存目录", justify="right")
    acct_table.add_column("占用空间", justify="right", style=f"bold {C_WARN}")

    for i, a in enumerate(accounts, 1):
        key = str(a.base_path.resolve()).lower()
        size = scanned_by_account.get(key, _account_size(a))
        acct_table.add_row(
            str(i),
            f"[{_cat_color('cache')}]{APP_LABELS.get(a.app, a.app)}[/]",
            a.account_id,
            str(len(a.cache_dirs)),
            humanize_size(size),
        )

    if not accounts:
        acct_table.add_row(
            "-", "[dim]未检测到任何微信/企业微信账号[/]", "", "", ""
        )

    # —— 体积分布条形图 ——
    size_by_cat = agg.get("size_by_category", {})
    total = agg.get("total_size", 0) or 1
    chart_lines: List[Text] = []
    for cat in ALL_CATEGORIES:
        sz = size_by_cat.get(cat, 0)
        if sz == 0 and not accounts:
            chart_lines.append(
                Text.assemble(
                    (f"{_cat_label(cat):　<6}", _cat_color(cat)),
                    ("  ──────────  ", C_DIM),
                    ("0 B", C_DIM),
                )
            )
            continue
        frac = sz / total if total else 0
        bar_len = max(1, int(frac * 24))
        bar = "█" * bar_len + "░" * (24 - bar_len)
        chart_lines.append(
            Text.assemble(
                (f"{_cat_label(cat):　<6}", _cat_color(cat)),
                (f"  {bar}  ", _cat_color(cat)),
                (humanize_size(sz), "bold white"),
                (f"  {frac*100:5.1f}%", C_DIM),
            )
        )

    chart_group = Group(
        Text("📊 缓存体积分布（按类型）", style=f"bold {C_ACCENT}"),
        Text(""),
        *chart_lines,
    )

    body = Group(
        Text.from_markup(
            f"📱 微信账号: [bold]{summary['wechat']}[/]  "
            f"🏢 企业微信账号: [bold]{summary['wecom']}[/]  "
            f"📁 缓存目录: [bold]{summary['cache_dirs']}[/]"
        ),
        Text(""),
        acct_table,
        Text(""),
        chart_group,
        Text(""),
        Text.from_markup(
            f"💾 待清理总量: [bold {C_WARN}]{agg.get('size_human','0 B')}[/]"
            f"  ·  文件数: [bold]{agg.get('total_count',0)}[/]"
            f"  ·  账号数: [bold]{agg.get('account_count',0)}[/]",
            style=f"bold {C_OK}",
        ),
    )

    console.print(Panel(body, border_style=C_PRIMARY, padding=(1, 2)))


def _cat_label(cat: str) -> str:
    from wechat_sweeper.detector import CATEGORY_LABELS
    return CATEGORY_LABELS.get(cat, cat)


def _account_size(account: Account) -> int:
    from wechat_sweeper.utils import directory_size
    total = 0
    for cd in account.cache_dirs:
        total += directory_size(cd.path)
    return total


def render_scan_detail(results: List[ScanResult], console: Optional[Console] = None) -> None:
    """渲染每个账号的扫描明细表。"""
    console = console or new_console()
    for r in results:
        if not r.files and not r.account.cache_dirs:
            continue
        t = Table(
            title=f"📋 {r.account.display_name}",
            box=box.SIMPLE_HEAVY,
            title_style=f"bold {C_ACCENT}",
            expand=True,
        )
        t.add_column("类型", style=_cat_color("file"))
        t.add_column("文件数", justify="right")
        t.add_column("占用", justify="right", style=f"bold {C_WARN}")
        t.add_column("示例文件（前 3 个）", overflow="fold")
        sbc = r.size_by_category()
        cbc = r.count_by_category()
        for cat in ALL_CATEGORIES:
            if cbc.get(cat, 0) == 0:
                continue
            samples = [f.path.name for f in r.files if f.category == cat][:3]
            t.add_row(
                _cat_label(cat),
                str(cbc.get(cat, 0)),
                humanize_size(sbc.get(cat, 0)),
                "  ".join(samples) if samples else "—",
            )
        console.print(t)
        if r.errors:
            console.print(f"  [dim]⚠ 跳过 {len(r.errors)} 个不可读项[/]")


def render_clean_report(report: CleanReport, console: Optional[Console] = None) -> None:
    """渲染清理结果汇总。"""
    console = console or new_console()
    if report.dry_run:
        title = "🧪 Dry-Run 预览（未删除任何文件）"
        accent = C_WARN
    else:
        title = "✨ 清理完成"
        accent = C_OK

    body = Group(
        Text.from_markup(f"🗂  候选文件: [bold]{report.total_files}[/]"),
        Text.from_markup(f"♻️  移入回收站: [bold]{report.trashed}[/]")
        if not report.dry_run else Text.from_markup(f"♻️  拟清理: [bold]{report.total_files}[/]"),
        Text.from_markup(f"📦 暂存本地回收站: [bold]{report.trashed_local}[/]")
        if (not report.dry_run and report.trashed_local) else Text(""),
        Text.from_markup(f"🗑  永久删除: [bold]{report.deleted}[/]") if not report.dry_run else Text(""),
        Text.from_markup(f"⏭  跳过: [bold]{report.skipped}[/]") if report.skipped else Text(""),
        Text.from_markup(f"⚠  错误: [bold red]{report.errors}[/]") if report.errors else Text(""),
        Text(""),
        Text.from_markup(
            f"💾 {'预计释放' if report.dry_run else '已释放'}: "
            f"[bold {accent}]{report.freed_human}[/]",
            style=f"bold {accent}",
        ),
        Text.from_markup(
            f"[dim]本地回收站：{report.managed_trash_dir}（可用 wechat-sweeper trash 管理）[/]"
        ) if report.managed_trash_dir else Text(""),
    )
    console.print(Panel(body, title=title, border_style=accent, padding=(1, 2)))


def make_progress(console: Optional[Console] = None):
    """构造一个 rich Progress 实例（用于清理进度）。"""
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(complete_style="bright_magenta", finished_style="bright_green"),
        TaskProgressColumn(),
        TextColumn("[dim]{task.fields[file]}[/]"),
        console=console or new_console(),
        transient=False,
    )


def progress_callback_factory(progress: Progress, task_id):
    """把 rich Progress 包装成 cleaner 可用的 (done,total,path)->None 回调。"""
    def _cb(done: int, total: int, path: str) -> None:
        fname = Path(path).name
        progress.update(task_id, completed=done, total=total, file=fname)
    return _cb


def capture(render_fn) -> str:
    """将任意渲染函数的输出捕获为字符串（用于测试/截图校验）。"""
    buf = StringIO()
    console = new_console(file=buf)
    render_fn(console)
    return buf.getvalue()
