"""用户配置持久化。

将用户的清理偏好（启用的文件类型、保留天数、是否移入回收站、自定义数据目录等）
保存为 JSON，默认位于 ``~/.config/wechatsweeper/config.json``（macOS/Linux）
或 ``%APPDATA%\\WeChatSweeper\\config.json``（Windows）。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional


def default_config_path() -> Path:
    """返回默认配置文件路径。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "WeChatSweeper" / "config.json"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "wechatsweeper" / "config.json"
    return Path.home() / ".config" / "wechatsweeper" / "config.json"


@dataclass
class Settings:
    """用户设置。"""
    categories: List[str] = field(default_factory=lambda: ["file", "video", "image"])
    days: int = 365
    use_trash: bool = True          # True=移入回收站；False=永久删除
    min_size: int = 0               # 仅清理大于该字节数的文件（0=不限）
    custom_roots: List[str] = field(default_factory=list)  # 自定义微信数据目录
    auto_clean: bool = False        # 是否启用定时清理
    auto_clean_interval_hours: int = 168  # 默认每周

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


class Config:
    """配置读写。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or default_config_path()

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return Settings.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return Settings()

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(settings.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def reset(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def load_settings(path: Optional[Path] = None) -> Settings:
    return Config(path).load()


def save_settings(settings: Settings, path: Optional[Path] = None) -> Path:
    cfg = Config(path)
    cfg.save(settings)
    return cfg.path
