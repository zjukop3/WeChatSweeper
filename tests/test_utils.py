"""工具函数测试。"""
from __future__ import annotations

import time
from pathlib import Path

from wechat_sweeper.utils import (
    classify_ext,
    clamp,
    humanize_size,
    is_older_than,
)


def test_humanize_size():
    assert humanize_size(0) == "0 B"
    assert humanize_size(1023) == "1023 B"
    assert humanize_size(1024) == "1.00 KiB"
    assert "MiB" in humanize_size(5 * 1024 * 1024)
    assert "GiB" in humanize_size(3 * 1024 ** 3)


def test_classify_ext():
    assert classify_ext(".jpg") == "image"
    assert classify_ext(".MP4") == "video"
    assert classify_ext(".pdf") == "file"
    assert classify_ext(".mp3") == "audio"
    assert classify_ext(".unknown") == "other"


def test_is_older_than(tmp_path: Path):
    f = tmp_path / "old.txt"
    f.write_text("x")
    now = time.time()
    old_ts = now - 400 * 86400
    import os
    os.utime(f, (old_ts, old_ts))
    assert is_older_than(f, 365, now=now) is True
    assert is_older_than(f, 500, now=now) is False
    assert is_older_than(f, 0, now=now) is True   # 不过滤


def test_clamp():
    assert clamp(5, 0, 10) == 5
    assert clamp(-1, 0, 10) == 0
    assert clamp(99, 0, 10) == 10
