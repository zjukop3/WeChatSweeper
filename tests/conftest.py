"""pytest 共享夹具：构造合成微信数据目录。"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest


OLD_TS = time.time() - 400 * 86400   # 400 天前
NEW_TS = time.time() - 10 * 86400    # 10 天前


def _write_file(path: Path, size: int, mtime: float, seed: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunk = (seed * 1024).encode()
    with open(path, "wb") as f:
        remaining = size
        while remaining > 0:
            n = min(len(chunk), remaining)
            f.write(chunk[:n])
            remaining -= n
    os.utime(path, (mtime, mtime))


@pytest.fixture
def fake_wechat_root(tmp_path: Path) -> Path:
    """构造一个含个人微信 + 企业微信的合成根目录。"""
    root = tmp_path / "WeChatData"

    # 个人微信（容器风格路径）
    wx = root / "com.tencent.xinWeChat" / "2.0b4.0.9" / "wxid_abc1234567" / "FileStorage"
    _write_file(wx / "File" / "report.pdf", 2 * 1024 * 1024, OLD_TS)        # 旧
    _write_file(wx / "File" / "today.zip", 4 * 1024 * 1024, NEW_TS)        # 新
    _write_file(wx / "Video" / "meeting.mp4", 15 * 1024 * 1024, OLD_TS)    # 旧
    _write_file(wx / "Video" / "recent.mp4", 6 * 1024 * 1024, NEW_TS)      # 新
    _write_file(wx / "Image" / "photo.jpg", 3 * 1024 * 1024, OLD_TS)        # 旧
    _write_file(wx / "Image" / "fresh.jpg", 2 * 1024 * 1024, NEW_TS)        # 新
    _write_file(wx / "Cache" / "thumb.dat", 512 * 1024, OLD_TS)            # 旧
    _write_file(wx / "Attach" / "doc.xlsx", 1 * 1024 * 1024, OLD_TS)       # 旧
    # 一个文字聊天记录库（绝不应被清理）
    _write_file(wx.parent / "Message" / "chat.db", 1024, OLD_TS)

    # 企业微信
    wecom = root / "WXWork" / "Data" / "corp_user_001" / "FileStorage"
    _write_file(wecom / "File" / "contract.pdf", 3 * 1024 * 1024, OLD_TS)
    _write_file(wecom / "Video" / "training.mp4", 20 * 1024 * 1024, OLD_TS)
    _write_file(wecom / "Image" / "banner.png", 2 * 1024 * 1024, OLD_TS)
    _write_file(wecom / "Cache" / "tmp.dat", 768 * 1024, OLD_TS)
    _write_file(wecom / "Attach" / "spec.docx", 1 * 1024 * 1024, OLD_TS)

    return root
