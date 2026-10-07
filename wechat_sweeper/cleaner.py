"""清理执行器：将扫描到的文件安全移入回收站。

安全原则：
1. 默认 "移入回收站"（send2trash），可恢复，绝不直接 unlink；
2. 提供 dry-run 模式，只报告将删除哪些文件，不动任何数据；
3. 永久删除需显式 ``permanent=True``；
4. 每个文件删除前后都校验路径仍在受信任的缓存目录内，防止符号链接逃逸。
"""
from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from send2trash import send2trash

from wechat_sweeper.detector import Account
from wechat_sweeper.scanner import FileEntry, ScanResult
from wechat_sweeper.utils import humanize_size


ProgressFn = Callable[[int, int, str], None]


@dataclass
class CleanOutcome:
    """单个文件的清理结果。"""
    path: Path
    size: int
    action: str        # 'trashed' / 'deleted' / 'skipped' / 'error' / 'dry-run'
    error: Optional[str] = None

    @property
    def size_human(self) -> str:
        return humanize_size(self.size)


@dataclass
class CleanReport:
    """一次清理任务的汇总。"""
    total_files: int = 0
    freed_bytes: int = 0
    trashed: int = 0             # 移入系统回收站
    trashed_local: int = 0       # 回退到本地托管回收站
    deleted: int = 0            # 永久删除
    skipped: int = 0
    errors: int = 0
    dry_run: bool = False
    managed_trash_dir: Optional[str] = None   # 本次使用的本地托管回收站（若有）
    outcomes: List[CleanOutcome] = field(default_factory=list)

    @property
    def freed_human(self) -> str:
        return humanize_size(self.freed_bytes)

    @property
    def succeeded(self) -> int:
        return self.trashed + self.trashed_local + self.deleted


@dataclass
class CleanOptions:
    permanent: bool = False      # True=永久删除；False=移入回收站
    dry_run: bool = False        # True=仅预览不执行
    confirm: Optional[Callable[[int, int], bool]] = None  # 确认回调(count,bytes)->bool
    progress: Optional[ProgressFn] = None


def _is_within(file_path: Path, base: Path) -> bool:
    """判断 file_path 是否位于 base 目录内（规范化后比较）。"""
    try:
        fp = file_path.resolve()
        bp = base.resolve()
        return str(fp) == str(bp) or str(fp).startswith(str(bp) + os.sep)
    except OSError:
        return False


def _safe_parents(path: Path, cache_roots: List[Path]) -> bool:
    """确保文件确实位于某个缓存根下，防止符号链接逃逸。"""
    return any(_is_within(path, root) for root in cache_roots)


def collect_cache_roots(accounts: List[Account]) -> List[Path]:
    roots: List[Path] = []
    for a in accounts:
        for cd in a.cache_dirs:
            roots.append(cd.path)
    return roots


def managed_trash_dir() -> Path:
    """本地托管回收站目录：当系统回收站不可用时回退到此。

    默认 ``~/.wechat-sweeper/trash/``；可用环境变量 ``WECHATSWEeper_TRASH_DIR``
    覆盖（便于在容器/CI 或受限目录中运行）。用户可用 ``wechat-sweeper trash`` 管理。
    """
    override = os.environ.get("WECHATSWEeper_TRASH_DIR")
    if override:
        return Path(os.path.expanduser(override))
    return Path.home() / ".wechat-sweeper" / "trash"


def _move_to_managed_trash(src: Path, run_stamp: str) -> Path:
    """把文件移入本地托管回收站，保留相对路径，便于事后核对。

    冲突时在文件名后追加计数。
    """
    base = managed_trash_dir() / run_stamp
    # 保留原路径末 4 段，便于辨认来源
    parts = src.parts
    tail = Path(*parts[-4:]) if len(parts) >= 4 else src.name
    dst = base / tail
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        stem, suffix = dst.stem, dst.suffix
        i = 1
        while True:
            cand = dst.with_name(f"{stem} ({i}){suffix}")
            if not cand.exists():
                dst = cand
                break
            i += 1
    shutil.move(str(src), str(dst))
    return dst


def managed_trash_size() -> int:
    """统计本地托管回收站占用字节数。"""
    from wechat_sweeper.utils import iter_files
    d = managed_trash_dir()
    if not d.exists():
        return 0
    total = 0
    for p in iter_files(d):
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


def empty_managed_trash() -> int:
    """清空本地托管回收站，返回清理的字节数。"""
    d = managed_trash_dir()
    if not d.exists():
        return 0
    freed = managed_trash_size()
    shutil.rmtree(d, ignore_errors=True)
    return freed


def clean_scan(
    scan_results: List[ScanResult],
    accounts: List[Account],
    options: CleanOptions,
) -> CleanReport:
    """根据扫描结果执行清理。

    :param scan_results: 扫描器产出的结果列表（与 accounts 一一对应）。
    :param accounts: 对应的账号列表，用于校验路径边界。
    :param options: 清理选项。
    """
    report = CleanReport(dry_run=options.dry_run)
    all_files: List[FileEntry] = []
    for r in scan_results:
        all_files.extend(r.files)

    total_count = len(all_files)
    total_bytes = sum(f.size for f in all_files)
    report.total_files = total_count

    # 确认回调
    if options.confirm is not None:
        try:
            if not options.confirm(total_count, total_bytes):
                report.skipped = total_count
                return report
        except Exception:
            report.skipped = total_count
            return report

    if options.dry_run:
        for f in all_files:
            outcome = CleanOutcome(path=f.path, size=f.size, action="dry-run")
            report.outcomes.append(outcome)
            report.freed_bytes += f.size
        return report

    cache_roots = collect_cache_roots(accounts)
    progress = options.progress
    done = 0
    run_stamp = time.strftime("%Y%m%d-%H%M%S")
    used_managed_trash = False

    for f in all_files:
        action = "trashed" if not options.permanent else "deleted"
        outcome = CleanOutcome(path=f.path, size=f.size, action=action)
        try:
            # 边界校验
            if not _safe_parents(f.path, cache_roots):
                outcome.action = "skipped"
                outcome.error = "路径不在受信任缓存目录内，已跳过"
                report.skipped += 1
                report.outcomes.append(outcome)
                continue

            if not f.path.exists():
                outcome.action = "skipped"
                outcome.error = "文件已不存在"
                report.skipped += 1
                report.outcomes.append(outcome)
                continue

            if options.permanent:
                try:
                    os.remove(f.path)
                except IsADirectoryError:
                    shutil.rmtree(f.path, ignore_errors=False)
                outcome.action = "deleted"
                report.deleted += 1
            else:
                try:
                    send2trash(str(f.path))
                    outcome.action = "trashed"
                    report.trashed += 1
                except Exception as trash_err:
                    # 系统回收站不可用（权限/沙盒）→ 回退到本地托管回收站
                    dst = _move_to_managed_trash(f.path, run_stamp)
                    outcome.action = "trashed-local"
                    outcome.error = f"系统回收站失败，已暂存至 {dst}（原因：{trash_err}）"
                    report.trashed_local += 1
                    used_managed_trash = True

            report.freed_bytes += f.size
        except Exception as e:  # noqa: BLE001 - 清理时务必吞掉单文件错误
            outcome.action = "error"
            outcome.error = str(e)
            report.errors += 1
        finally:
            report.outcomes.append(outcome)
            done += 1
            if progress is not None:
                try:
                    progress(done, total_count, str(f.path))
                except Exception:
                    pass

    if used_managed_trash:
        report.managed_trash_dir = str(managed_trash_dir())
    return report
