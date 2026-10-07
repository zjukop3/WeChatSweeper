"""自动检测本机微信 / 企业微信账号及其缓存目录。

支持 macOS、Windows、Linux（含官方 Linux 微信与 Wine 微信）。
检测策略：枚举各平台候选根目录，做有界深度搜索，凡直接包含 ``FileStorage``
子目录的目录即视为一个账号目录，再在其中定位已知缓存子目录
（File / Video / Image / Cache / Attach / CDNFileStorage）。

设计目标：宁可漏检也不要误判——只清理 ``FileStorage`` 下的媒体与缓存，
绝不触碰存放文字聊天记录的 ``Message`` 数据库，保证安全。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from wechat_sweeper.utils import current_platform, safe_expanduser


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

# 缓存类别（对外稳定标识）
CATEGORY_FILE = "file"
CATEGORY_VIDEO = "video"
CATEGORY_IMAGE = "image"
CATEGORY_CACHE = "cache"
CATEGORY_ATTACH = "attach"

ALL_CATEGORIES = (
    CATEGORY_FILE,
    CATEGORY_VIDEO,
    CATEGORY_IMAGE,
    CATEGORY_CACHE,
    CATEGORY_ATTACH,
)

CATEGORY_LABELS = {
    CATEGORY_FILE: "文件",
    CATEGORY_VIDEO: "视频",
    CATEGORY_IMAGE: "图片",
    CATEGORY_CACHE: "缓存",
    CATEGORY_ATTACH: "附件",
}

# FileStorage 下已知的缓存子目录名 → 类别
KNOWN_CACHE_SUBDIRS = {
    "File": CATEGORY_FILE,
    "Video": CATEGORY_VIDEO,
    "Image": CATEGORY_IMAGE,
    "Cache": CATEGORY_CACHE,
    "Attach": CATEGORY_ATTACH,
    "CDNFileStorage": CATEGORY_CACHE,
    "General": CATEGORY_CACHE,        # 部分版本存放的杂项缓存
    "HDVideo": CATEGORY_VIDEO,        # 高清视频
    "HDImage": CATEGORY_IMAGE,
}

APP_WECHAT = "wechat"   # 个人微信
APP_WECOM = "wecom"     # 企业微信

APP_LABELS = {
    APP_WECHAT: "微信",
    APP_WECOM: "企业微信",
}


@dataclass
class CacheDir:
    """一个缓存子目录。"""
    category: str        # file/video/image/cache/attach
    rel_name: str        # 子目录名（如 File、Video）
    path: Path           # 绝对路径

    def exists(self) -> bool:
        try:
            return self.path.is_dir()
        except OSError:
            return False


@dataclass
class Account:
    """一个被检测到的微信 / 企业微信账号。"""
    account_id: str          # 账号目录名（wxid 或 corp_id 等）
    app: str                 # wechat / wecom
    base_path: Path          # 账号根目录（包含 FileStorage 的目录）
    cache_dirs: List[CacheDir] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return f"{APP_LABELS.get(self.app, self.app)} · {self.account_id}"

    @property
    def file_storage(self) -> Path:
        return self.base_path / "FileStorage"


# ---------------------------------------------------------------------------
# 平台候选根目录
# ---------------------------------------------------------------------------

def _macos_roots() -> List[Path]:
    home = Path.home()
    roots = [
        home / "Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/com.tencent.xinWeChat",
        home / "Library/Application Support/com.tencent.xinWeChat",
        home / "Library/Containers/com.tencent.xinWeChat/Data/Documents",
        # 企业微信
        home / "Library/Containers/com.tencent.WeWork/Data/Library/Application Support/WXWork",
        home / "Library/Application Support/WXWork",
        home / "Library/Containers/com.tencent.WeWork/Data/Documents",
    ]
    return roots


def _windows_roots() -> List[Path]:
    roots: List[Path] = []
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        up = Path(userprofile)
        roots += [
            up / "Documents/WeChat Files",
            up / "Documents/xwechat_files",
            up / "Documents/WXWork",
        ]
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        roots += [
            Path(appdata) / "Tencent/WeChat",
            Path(appdata) / "Tencent/xwechat",
        ]
    if localappdata:
        roots += [
            Path(localappdata) / "Tencent/WeChat",
            Path(localappdata) / "Tencent/xwechat",
        ]
    # 兜底：常见盘符下的 Documents
    for drive in ("C:", "D:", "E:"):
        try:
            docs = Path(f"{drive}/Users") / os.environ.get("USERNAME", "") / "Documents"
            roots += [docs / "WeChat Files", docs / "WXWork", docs / "xwechat_files"]
        except Exception:
            continue
    return roots


def _linux_roots() -> List[Path]:
    home = Path.home()
    roots = [
        home / ".config/tencent-wxwechat",
        home / ".config/tencent/wxwechat",
        home / ".config/wechat",
        home / ".local/share/tencent",
        home / ".local/share/wechat",
        # Wine
        home / ".wine/drive_c/users",
    ]
    return roots


def candidate_roots(platform: Optional[str] = None) -> List[Path]:
    """返回当前平台的候选根目录列表（不保证存在）。"""
    plat = platform or current_platform()
    if plat == "macos":
        return _macos_roots()
    if plat == "windows":
        return _windows_roots()
    return _linux_roots()


# ---------------------------------------------------------------------------
# 路径到 App 类型的推断
# ---------------------------------------------------------------------------

_WECOM_MARKERS = ("wework", "wxwork", "WeCom", "企业微信")
_WECHAT_MARKERS = ("xinwechat", "wechat", "xwechat", "wxwechat", "tencent-wxwechat", "微信")


def infer_app(path: Path) -> str:
    s = str(path).lower()
    if any(m.lower() in s for m in _WECOM_MARKERS):
        return APP_WECOM
    return APP_WECHAT


# ---------------------------------------------------------------------------
# 核心搜索
# ---------------------------------------------------------------------------

def _looks_like_account_id(name: str) -> bool:
    """目录名是否像是账号 ID（wxid_、wxid、字母数字串、corpid 等）。"""
    if not name:
        return False
    low = name.lower()
    if low.startswith("wxid"):
        return True
    if low in ("filestorage", "message", "files", "general", "cache"):
        return False
    if low.replace("_", "").replace("-", "").isalnum() and len(name) >= 4:
        return True
    return False


def _find_cache_dirs(account_base: Path) -> List[CacheDir]:
    """在账号根目录下定位缓存子目录。"""
    result: List[CacheDir] = []
    # 优先 FileStorage 子目录
    file_storage = account_base / "FileStorage"
    search_bases = []
    if file_storage.is_dir():
        search_bases.append(file_storage)
    # 兼容：部分布局把 File/Video 直接放在账号根下
    search_bases.append(account_base)

    seen = set()
    for base in search_bases:
        try:
            entries = list(base.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name
            cat = KNOWN_CACHE_SUBDIRS.get(name)
            if cat is None:
                continue
            key = str(entry.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(CacheDir(category=cat, rel_name=name, path=entry))
    return result


def _search_root(root: Path, max_depth: int = 4, found: Optional[set] = None) -> List[Account]:
    """在单个候选根下做有界深度搜索，返回检测到的账号列表。"""
    found = found if found is not None else set()
    accounts: List[Account] = []

    if not root.exists():
        return accounts

    # BFS，限定深度，避免遍历巨大目录树
    try:
        current_level = [root]
    except OSError:
        return accounts

    for depth in range(max_depth + 1):
        next_level: List[Path] = []
        for d in current_level:
            try:
                is_dir = d.is_dir()
            except OSError:
                continue
            if not is_dir:
                continue

            # 判定是否为账号目录：直接包含 FileStorage，或直接包含已知缓存子目录
            has_filestorage = (d / "FileStorage").is_dir()
            cache_dirs = _find_cache_dirs(d) if (has_filestorage or _has_known_subdir(d)) else []
            if cache_dirs:
                key = str(d.resolve()).lower()
                if key not in found:
                    found.add(key)
                    app = infer_app(d)
                    accounts.append(
                        Account(
                            account_id=_derive_account_id(d, app),
                            app=app,
                            base_path=d,
                            cache_dirs=cache_dirs,
                        )
                    )
                # 找到账号后不再向下钻取其内部（其 FileStorage 由扫描器处理）
                continue

            if depth >= max_depth:
                continue
            try:
                for child in d.iterdir():
                    if child.is_dir():
                        next_level.append(child)
            except OSError:
                continue
        current_level = next_level
        if not current_level:
            break

    return accounts


def _has_known_subdir(d: Path) -> bool:
    try:
        for child in d.iterdir():
            if child.is_dir() and child.name in KNOWN_CACHE_SUBDIRS:
                return True
    except OSError:
        return False
    return False


def _derive_account_id(d: Path, app: str) -> str:
    """从账号目录路径推断账号标识。优先用目录名，否则用路径末两段。"""
    name = d.name
    if name and _looks_like_account_id(name):
        return name
    # 回退：用相对路径区分
    parent = d.parent.name
    if parent:
        return f"{parent}/{name}"
    return name or str(d)


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------

def detect_accounts(
    extra_roots: Optional[List[Path | str]] = None,
    platform: Optional[str] = None,
    app_filter: Optional[str] = None,
    include_platform_roots: bool = True,
) -> List[Account]:
    """自动检测所有微信 / 企业微信账号。

    :param extra_roots: 额外自定义根目录（用户通过 --root 指定的微信数据目录）。
    :param platform: 平台标识，默认自动判定。
    :param app_filter: 仅返回该类型账号（wechat / wecom），None 表示全部。
    :param include_platform_roots: 是否扫描平台默认候选目录。
        测试时可设为 False，仅依据 extra_roots 检测，结果确定。
    """
    roots: List[Path] = []
    if include_platform_roots:
        roots += candidate_roots(platform)
    if extra_roots:
        roots += [safe_expanduser(r) for r in extra_roots]

    seen_paths: set = set()
    accounts: List[Account] = []
    for root in roots:
        for acc in _search_root(root, found=seen_paths):
            accounts.append(acc)

    # 自定义根往往是账号目录本身或其父；做一次直接探测
    if extra_roots:
        for r in extra_roots:
            rp = safe_expanduser(r)
            if not rp.exists():
                continue
            # 若 r 本身就是账号目录
            for acc in _search_root(rp, max_depth=3, found=seen_paths):
                accounts.append(acc)

    if app_filter:
        accounts = [a for a in accounts if a.app == app_filter]

    # 去重并按 app、account_id 排序
    deduped: dict = {}
    for a in accounts:
        key = str(a.base_path.resolve()).lower()
        deduped.setdefault(key, a)
    return sorted(deduped.values(), key=lambda a: (a.app, a.account_id))


def summarize_accounts(accounts: List[Account]) -> dict:
    """返回账号概要统计（用于 UI）。"""
    by_app = {APP_WECHAT: 0, APP_WECOM: 0}
    for a in accounts:
        by_app[a.app] = by_app.get(a.app, 0) + 1
    return {
        "total_accounts": len(accounts),
        "wechat": by_app.get(APP_WECHAT, 0),
        "wecom": by_app.get(APP_WECOM, 0),
        "cache_dirs": sum(len(a.cache_dirs) for a in accounts),
    }
