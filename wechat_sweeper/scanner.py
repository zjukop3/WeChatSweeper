"""扫描缓存目录，按类型与时间过滤文件，统计体积。

扫描器只读不写，安全：它不会修改或删除任何文件，只负责枚举与统计，
真正的清理动作在 :mod:`wechat_sweeper.cleaner` 中完成。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from wechat_sweeper.detector import (
    ALL_CATEGORIES,
    CATEGORY_LABELS,
    Account,
    CacheDir,
)
from wechat_sweeper.utils import (
    classify_ext,
    humanize_size,
    is_older_than,
    iter_files,
)


@dataclass
class FileEntry:
    """一个被扫描到的候选文件。"""
    path: Path
    size: int
    mtime: float
    category: str          # 所属缓存目录类别（file/video/image/cache/attach）
    ext_category: str     # 按扩展名推断的类别（image/video/file/audio/other）
    account_id: str

    @property
    def size_human(self) -> str:
        return humanize_size(self.size)


@dataclass
class ScanResult:
    """一次扫描的结果集合。"""
    account: Account
    files: List[FileEntry] = field(default_factory=list)
    skipped: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

    @property
    def total_count(self) -> int:
        return len(self.files)

    def size_by_category(self) -> Dict[str, int]:
        sizes: Dict[str, int] = {c: 0 for c in ALL_CATEGORIES}
        for f in self.files:
            sizes[f.category] = sizes.get(f.category, 0) + f.size
        return sizes

    def count_by_category(self) -> Dict[str, int]:
        counts: Dict[str, int] = {c: 0 for c in ALL_CATEGORIES}
        for f in self.files:
            counts[f.category] = counts.get(f.category, 0) + 1
        return counts


@dataclass
class ScanOptions:
    """扫描选项。"""
    categories: Iterable[str] = field(default_factory=lambda: tuple(ALL_CATEGORIES))
    days: int = 365            # 仅扫描 mtime 早于 N 天前的文件；<=0 表示全部
    min_size: int = 0         # 仅扫描大于该字节数的文件；0 表示不限
    include_hidden: bool = False
    now: Optional[float] = None   # 注入用（测试）


def _is_hidden(name: str) -> bool:
    return name.startswith(".") or name.startswith("_")


def scan_account(account: Account, options: ScanOptions) -> ScanResult:
    """扫描单个账号的缓存目录。"""
    result = ScanResult(account=account)
    now = options.now
    wanted_cats = set(options.categories)

    for cache_dir in account.cache_dirs:
        if cache_dir.category not in wanted_cats:
            continue
        if not cache_dir.exists():
            continue
        for path in iter_files(cache_dir.path):
            try:
                name = path.name
                if not options.include_hidden and _is_hidden(name):
                    result.skipped += 1
                    continue

                st = path.stat()
                size = st.st_size
                mtime = st.st_mtime

                if options.min_size > 0 and size < options.min_size:
                    continue
                if not is_older_than(path, options.days, now=now):
                    continue

                result.files.append(
                    FileEntry(
                        path=path,
                        size=size,
                        mtime=mtime,
                        category=cache_dir.category,
                        ext_category=classify_ext(path.suffix),
                        account_id=account.account_id,
                    )
                )
            except OSError as e:
                result.errors.append(f"{cache_dir.path}: {e}")
                continue

    return result


def scan_accounts(accounts: List[Account], options: ScanOptions) -> List[ScanResult]:
    """扫描多个账号。"""
    return [scan_account(a, options) for a in accounts]


def aggregate(results: List[ScanResult]) -> dict:
    """汇总多个账号扫描结果。"""
    total_size = 0
    total_count = 0
    size_by_cat: Dict[str, int] = {c: 0 for c in ALL_CATEGORIES}
    count_by_cat: Dict[str, int] = {c: 0 for c in ALL_CATEGORIES}
    for r in results:
        total_size += r.total_size
        total_count += r.total_count
        sbc = r.size_by_category()
        cbc = r.count_by_category()
        for c in ALL_CATEGORIES:
            size_by_cat[c] += sbc.get(c, 0)
            count_by_cat[c] += cbc.get(c, 0)
    return {
        "total_size": total_size,
        "total_count": total_count,
        "size_human": humanize_size(total_size),
        "size_by_category": size_by_cat,
        "count_by_category": count_by_cat,
        "account_count": len(results),
        "categories": [c for c in ALL_CATEGORIES if count_by_cat[c] > 0],
    }
