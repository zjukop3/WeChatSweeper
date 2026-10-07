"""通用工具：平台判定、字节人类化、路径安全处理、时间过滤等。"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def current_platform() -> str:
    """返回标准化平台标识：'macos' / 'windows' / 'linux'。"""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return "linux"


def humanize_size(num_bytes: float) -> str:
    """将字节数转为人类可读字符串，二进制单位 (KiB/MiB/GiB)。"""
    if num_bytes is None or num_bytes < 0:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    size = float(num_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.2f} {units[idx]}"


def file_mtime_ts(path: Path) -> float:
    """安全获取文件修改时间戳，失败返回 0。"""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def is_older_than(path: Path, days: int, now: float | None = None) -> bool:
    """判断文件 mtime 是否早于 `days` 天前。

    days <= 0 视为不过滤（始终返回 True，即"全部纳入"）。
    """
    if days <= 0:
        return True
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    return file_mtime_ts(path) + days * 86400 <= now


def safe_expanduser(path: str | os.PathLike) -> Path:
    """展开 ~ 与环境变量。"""
    return Path(os.path.expandvars(os.path.expanduser(str(path))))


def iter_files(root: Path) -> Iterable[Path]:
    """递归遍历目录下所有常规文件，跳过符号链接指向自身的环。"""
    try:
        for p in root.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    yield p
            except OSError:
                continue
    except OSError:
        return


def directory_size(root: Path) -> int:
    """计算目录下所有文件总字节数。"""
    total = 0
    for p in iter_files(root):
        try:
            total += p.stat().st_size
        except OSError:
            continue
    return total


# 按文件类型分类的扩展名集合（用于在缓存目录内进一步细分时使用）。
EXT_BY_CATEGORY = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".tiff", ".dat"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v", ".3gp"},
    "file": {
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf",
        ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2",
        ".txt", ".csv", ".json", ".xml", ".html",
        ".exe", ".dmg", ".apk", ".ipa", ".psd", ".ai",
    },
    "audio": {".mp3", ".m4a", ".aac", ".wav", ".amr", ".wma", ".ogg"},
    "other": set(),
}


def classify_ext(ext: str) -> str:
    """根据扩展名返回所属类别。"""
    ext = ext.lower()
    for cat, exts in EXT_BY_CATEGORY.items():
        if ext in exts:
            return cat
    return "other"


def clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))
