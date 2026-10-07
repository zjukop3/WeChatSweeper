"""命令行入口。

用法示例：
    wechat-sweeper scan                 # 检测账号并扫描缓存（只读）
    wechat-sweeper clean --dry-run      # 预览将清理哪些文件
    wechat-sweeper clean --yes          # 真正清理（移入回收站）
    wechat-sweeper clean --days 180 --types video image
    wechat-sweeper config set days 180
    wechat-sweeper schedule install --hours 168
    wechat-sweeper                      # 交互式菜单
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

import click

from wechat_sweeper import __version__
from wechat_sweeper import ui as U
from wechat_sweeper.cleaner import (
    CleanOptions,
    clean_scan,
    empty_managed_trash,
    managed_trash_dir,
    managed_trash_size,
)
from wechat_sweeper.config import Config, Settings, load_settings, save_settings
from wechat_sweeper.detector import (
    ALL_CATEGORIES,
    CATEGORY_LABELS,
    APP_LABELS,
    detect_accounts,
)
from wechat_sweeper.scanner import ScanOptions, aggregate, scan_accounts
from wechat_sweeper.scheduler import install as sched_install
from wechat_sweeper.scheduler import status as sched_status
from wechat_sweeper.scheduler import uninstall as sched_uninstall
from wechat_sweeper.utils import humanize_size


def _build_options(settings: Settings, days: Optional[int],
                   types: Optional[List[str]], min_size: Optional[int]) -> ScanOptions:
    cats = tuple(types) if types else tuple(settings.categories)
    # 校验类别
    cats = tuple(c for c in cats if c in ALL_CATEGORIES)
    if not cats:
        cats = tuple(settings.categories) or ("file", "video", "image")
    return ScanOptions(
        categories=cats,
        days=settings.days if days is None else days,
        min_size=settings.min_size if min_size is None else min_size,
    )


def _do_scan(console, settings: Settings, days, types, min_size,
             extra_roots: Optional[List[str]] = None):
    accounts = detect_accounts(extra_roots=extra_roots or settings.custom_roots)
    options = _build_options(settings, days, types, min_size)
    results = scan_accounts(accounts, options)
    agg = aggregate(results)
    return accounts, results, options, agg


# ---------------------------------------------------------------------------
@click.group(invoke_without_command=True, context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="WeChatSweeper")
@click.pass_context
def main(ctx: click.Context) -> None:
    """🧹 WeChatSweeper —— 跨平台微信/企业微信缓存清理终端工具。

    不带子命令时进入交互式菜单。常见用法见上方模块 docstring。
    """
    if ctx.invoked_subcommand is None:
        interactive()


@main.command()
@click.option("--root", "roots", multiple=True, help="自定义微信数据目录（可多次指定）。")
@click.option("--days", type=int, help="仅清理 N 天前的文件，覆盖配置。")
@click.option("--types", "types", multiple=True,
              type=click.Choice(ALL_CATEGORIES, case_sensitive=False),
              help="文件类型，可多选：file video image cache attach。")
@click.option("--min-size", type=int, help="仅清理大于该字节数的文件。")
def scan(roots, days, types, min_size) -> None:
    """🔍 扫描缓存：检测账号并统计可清理体积（只读，不删除）。"""
    console = U.new_console()
    U.render_banner(console)
    settings = load_settings()
    console.print("[dim]⏳ 正在检测微信/企业微信账号…[/]")
    accounts, results, options, agg = _do_scan(
        console, settings, days, list(types) if types else None, min_size,
        extra_roots=list(roots) or None,
    )
    console.print()
    U.render_dashboard(accounts, agg, results, console)
    console.print()
    if accounts:
        U.render_scan_detail(results, console)
    else:
        console.print(
            "[bold yellow]未检测到微信数据。[/] 可用 "
            "[cyan]wechat-sweeper scan --root <你的微信数据目录>[/] 手动指定，"
            "或运行 [cyan]wechat-sweeper config set root <目录>[/] 持久保存。"
        )


@main.command()
@click.option("--root", "roots", multiple=True, help="自定义微信数据目录。")
@click.option("--days", type=int, help="仅清理 N 天前的文件。")
@click.option("--types", "types", multiple=True,
              type=click.Choice(ALL_CATEGORIES, case_sensitive=False),
              help="文件类型，可多选。")
@click.option("--dry-run", is_flag=True, help="预览模式：只报告不删除。")
@click.option("--permanent", is_flag=True, help="永久删除（默认移入回收站）。")
@click.option("--yes", "-y", is_flag=True, help="跳过交互确认直接执行。")
def clean(roots, days, types, dry_run, permanent, yes) -> None:
    """♻️ 清理缓存：扫描后移入回收站（--permanent 永久删除）。"""
    console = U.new_console()
    U.render_banner(console)
    settings = load_settings()
    accounts, results, options, agg = _do_scan(
        console, settings, days, list(types) if types else None, None,
        extra_roots=list(roots) or None,
    )
    console.print()
    U.render_dashboard(accounts, agg, results, console)

    if not accounts or agg["total_count"] == 0:
        console.print("[bold green]没有可清理的文件，你的微信很干净！✨[/]")
        return

    # 确认
    def confirm(count: int, bytes_: int) -> bool:
        if yes:
            return True
        console.print()
        console.print(f"将{'预览' if dry_run else '清理'} [bold]{count}[/] 个文件，"
                      f"共 [bold yellow]{humanize_size(bytes_)}[/]"
                      + ("（永久删除，不可恢复）" if permanent else "（移入回收站，可恢复）"))
        if dry_run:
            return True
        return click.confirm("确认执行？", default=False, abort=False)

    clean_options = CleanOptions(
        permanent=permanent,
        dry_run=dry_run,
        confirm=confirm if not yes else None,
    )

    # 进度条
    progress = U.make_progress(console)
    task_id = progress.add_task("清理中", total=agg["total_count"], file="")
    clean_options.progress = U.progress_callback_factory(progress, task_id)

    if not dry_run and not yes:
        # 先打印待清理量，等用户确认
        pass

    with progress:
        report = clean_scan(results, accounts, clean_options)

    console.print()
    U.render_clean_report(report, console)

    # 明细
    if dry_run and report.outcomes:
        t = _build_outcome_table(report)
        console.print(t)


def _build_outcome_table(report):
    from rich.table import Table
    from rich import box
    t = Table(title="🧪 拟清理文件明细（前 50 项）", box=box.SIMPLE_HEAVY,
              title_style="bold bright_yellow", expand=True)
    t.add_column("#", style="grey70", width=4)
    t.add_column("应用")
    t.add_column("类型", style="bright_blue")
    t.add_column("大小", justify="right", style="bold bright_yellow")
    t.add_column("路径", overflow="fold")
    for i, o in enumerate(report.outcomes[:50], 1):
        t.add_row(str(i), "", o.path.parent.name, o.size_human, str(o.path))
    return t


@main.group()
def config() -> None:
    """⚙️ 用户配置：查看/修改清理偏好。"""
    pass


@config.command("show")
def config_show() -> None:
    """显示当前配置。"""
    console = U.new_console()
    s = load_settings()
    console.print()
    console.print("[bold bright_cyan]⚙️  当前配置[/]")
    console.print(f"  清理类型: [bold]{', '.join(CATEGORY_LABELS.get(c,c) for c in s.categories)}[/]")
    console.print(f"  保留天数: [bold]{s.days}[/] 天")
    console.print(f"  删除方式: [bold]{'移入回收站' if s.use_trash else '永久删除'}[/]")
    console.print(f"  最小体积: [bold]{humanize_size(s.min_size) if s.min_size else '不限'}[/]")
    console.print(f"  自定义目录: [bold]{s.custom_roots or '（无）'}[/]")
    console.print(f"  定时清理: [bold]{'开' if s.auto_clean else '关'}[/]"
                  f"  间隔 {s.auto_clean_interval_hours} 小时")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value) -> None:
    """设置某项配置，例：config set days 180 / config set types video,image"""
    console = U.new_console()
    s = load_settings()
    k = key.lower()
    if k == "days":
        s.days = max(0, int(value))
    elif k == "types":
        cats = [c.strip() for c in str(value).split(",") if c.strip()]
        bad = [c for c in cats if c not in ALL_CATEGORIES]
        if bad:
            raise click.BadParameter(f"未知类型: {bad}，可选: {list(ALL_CATEGORIES)}")
        s.categories = cats
    elif k in ("trash", "use_trash"):
        s.use_trash = str(value).lower() in ("1", "true", "yes", "on")
    elif k == "min_size":
        s.min_size = max(0, int(value))
    elif k in ("root", "roots"):
        s.custom_roots = [p.strip() for p in str(value).split(";") if p.strip()]
    elif k in ("auto_clean",):
        s.auto_clean = str(value).lower() in ("1", "true", "yes", "on")
    elif k in ("interval", "auto_clean_interval_hours"):
        s.auto_clean_interval_hours = max(1, int(value))
    else:
        raise click.BadParameter(f"未知配置项: {key}")
    save_settings(s)
    console.print(f"[green]✓[/] 已保存 {key} = {value}")


@config.command("reset")
def config_reset() -> None:
    """重置配置为默认。"""
    Config().reset()
    click.echo("✓ 配置已重置")


@main.group("schedule")
def schedule() -> None:
    """🕐 定时清理：安装/卸载/查询定时任务。"""
    pass


@schedule.command("install")
@click.option("--hours", type=int, default=168, help="间隔小时数，默认 168（一周）。")
def schedule_install(hours) -> None:
    """安装定时清理任务。"""
    console = U.new_console()
    r = sched_install(hours)
    console.print(f"[{'green' if r.ok else 'red'}]{'✓' if r.ok else '✗'}[/] {r.message}")
    if r.detail:
        console.print(f"[dim]{r.detail}[/]")


@schedule.command("uninstall")
def schedule_uninstall() -> None:
    """卸载定时清理任务。"""
    console = U.new_console()
    r = sched_uninstall()
    console.print(f"[{'green' if r.ok else 'red'}]{'✓' if r.ok else '✗'}[/] {r.message}")


@schedule.command("status")
def schedule_status() -> None:
    """查询定时任务状态。"""
    console = U.new_console()
    console.print(f"定时清理：[bold]{sched_status()}[/]")


@main.group("trash")
def trash_group() -> None:
    """🗑 管理本地托管回收站（系统回收站不可用时的暂存目录）。"""
    pass


@trash_group.command("path")
def trash_path() -> None:
    """显示本地托管回收站路径与占用。"""
    console = U.new_console()
    d = managed_trash_dir()
    sz = managed_trash_size()
    console.print(f"本地回收站路径: [bold cyan]{d}[/]")
    console.print(f"当前占用: [bold yellow]{humanize_size(sz)}[/]")


@trash_group.command("empty")
@click.confirmation_option(prompt="确认清空本地托管回收站？此操作不可恢复。")
def trash_empty() -> None:
    """清空本地托管回收站。"""
    console = U.new_console()
    freed = empty_managed_trash()
    console.print(f"[green]✓[/] 已清空本地回收站，释放 [bold yellow]{humanize_size(freed)}[/]")


# ---------------------------------------------------------------------------
def interactive() -> None:
    """交互式菜单（无子命令时调用）。"""
    console = U.new_console()
    U.render_banner(console)
    console.print("[dim]⏳ 正在检测微信/企业微信账号…[/]")
    settings = load_settings()
    accounts, results, options, agg = _do_scan(console, settings, None, None, None)
    U.render_dashboard(accounts, agg, results, console)

    if not accounts or agg["total_count"] == 0:
        console.print("[bold green]没有可清理的文件，你的微信很干净！✨[/]")
        console.print("[dim]提示：可用 scan --root <目录> 指定自定义数据目录。[/]")
        return

    console.print()
    console.print("[bold bright_cyan]选择操作：[/]")
    console.print("  [1] 🧪 预览将清理的文件（Dry-Run）")
    console.print("  [2] ♻️  清理（移入回收站，可恢复）")
    console.print("  [3] 🗑  永久删除（不可恢复）")
    console.print("  [4] ⚙️  修改配置（保留天数/类型）")
    console.print("  [q] 退出")
    choice = click.prompt("请选择", default="1", show_default=False)

    if choice == "q":
        return
    if choice == "4":
        days = click.prompt("保留天数（仅清理 N 天前的文件）", default=str(settings.days), type=int)
        types_str = click.prompt(
            "清理类型（逗号分隔：file,video,image,cache,attach）",
            default=",".join(settings.categories),
        )
        cats = [c.strip() for c in types_str.split(",") if c.strip()]
        cats = [c for c in cats if c in ALL_CATEGORIES] or list(settings.categories)
        settings.days = max(0, int(days))
        settings.categories = cats
        save_settings(settings)
        console.print("[green]✓ 配置已保存，重新扫描…[/]")
        accounts, results, options, agg = _do_scan(console, settings, None, cats, None)
        U.render_dashboard(accounts, agg, results, console)
        choice = click.prompt("选择操作 [1=预览 2=清理 q=退出]", default="1")

    dry_run = choice == "1"
    permanent = choice == "3"
    use_trash = not permanent

    def confirm(count, bytes_):
        console.print(f"\n将{'预览' if dry_run else '清理'} [bold]{count}[/] 个文件，"
                      f"共 [bold yellow]{humanize_size(bytes_)}[/]")
        if dry_run:
            return True
        return click.confirm("确认执行？", default=False)

    clean_options = CleanOptions(
        permanent=permanent,
        dry_run=dry_run,
        confirm=confirm,
    )
    progress = U.make_progress(console)
    task_id = progress.add_task("清理中", total=agg["total_count"], file="")
    clean_options.progress = U.progress_callback_factory(progress, task_id)
    with progress:
        report = clean_scan(results, accounts, clean_options)
    console.print()
    U.render_clean_report(report, console)


if __name__ == "__main__":
    main()
