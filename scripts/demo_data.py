"""生成合成微信数据目录，用于演示、截图与测试。

用法：
    python scripts/demo_data.py <输出目录>

会在输出目录下构造两个账号（一个个人微信、一个企业微信），
各自含 FileStorage/{File,Video,Image,Cache,Attach}，
并在其中放入若干"旧文件"（mtime 早于 365 天前）与"新文件"，
便于验证按时间过滤的逻辑。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

OLD_TS = time.time() - 400 * 86400   # 400 天前
NEW_TS = time.time() - 10 * 86400    # 10 天前


def _write_file(path: Path, size: int, mtime: float, content_seed: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunk = (content_seed * 1024).encode()
    with open(path, "wb") as f:
        remaining = size
        while remaining > 0:
            n = min(len(chunk), remaining)
            f.write(chunk[:n])
            remaining -= n
    os.utime(path, (mtime, mtime))


def build_wechat_account(root: Path, account_id: str) -> Path:
    base = root / account_id
    fs = base / "FileStorage"
    # 旧文件（应被清理）
    _write_file(fs / "File" / "report.pdf", 2 * 1024 * 1024, OLD_TS)
    _write_file(fs / "File" / "archive.zip", 8 * 1024 * 1024, OLD_TS)
    _write_file(fs / "Video" / "meeting.mp4", 15 * 1024 * 1024, OLD_TS)
    _write_file(fs / "Video" / "clip.mov", 5 * 1024 * 1024, OLD_TS)
    _write_file(fs / "Image" / "screenshot.png", 1 * 1024 * 1024, OLD_TS)
    _write_file(fs / "Image" / "photo.jpg", 3 * 1024 * 1024, OLD_TS)
    _write_file(fs / "Cache" / "thumb_0.dat", 512 * 1024, OLD_TS)
    _write_file(fs / "Attach" / "doc.xlsx", 1 * 1024 * 1024, OLD_TS)
    # 新文件（不应被清理，days=365 时）
    _write_file(fs / "File" / "today.zip", 4 * 1024 * 1024, NEW_TS)
    _write_file(fs / "Video" / "recent.mp4", 6 * 1024 * 1024, NEW_TS)
    _write_file(fs / "Image" / "fresh.jpg", 2 * 1024 * 1024, NEW_TS)
    return base


def build_wecom_account(root: Path, account_id: str) -> Path:
    base = root / account_id
    fs = base / "FileStorage"
    _write_file(fs / "File" / "contract.pdf", 3 * 1024 * 1024, OLD_TS)
    _write_file(fs / "Video" / "training.mp4", 20 * 1024 * 1024, OLD_TS)
    _write_file(fs / "Image" / "banner.png", 2 * 1024 * 1024, OLD_TS)
    _write_file(fs / "Cache" / "tmp_1.dat", 768 * 1024, OLD_TS)
    _write_file(fs / "Attach" / "spec.docx", 1 * 1024 * 1024, OLD_TS)
    return base


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/demo_data.py <输出目录>")
        return 1
    root = Path(sys.argv[1]).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    # 个人微信（容器风格）
    wx_root = root / "com.tencent.xinWeChat" / "2.0b4.0.9"
    build_wechat_account(wx_root, "wxid_abc1234567")
    # 企业微信
    wecom_root = root / "WXWork" / "Data"
    build_wecom_account(wecom_root, "corp_user_001")
    print(f"已生成合成微信数据于：{root}")
    print(f"  个人微信: {wx_root / 'wxid_abc1234567'}")
    print(f"  企业微信: {wecom_root / 'corp_user_001'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
