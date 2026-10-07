"""扫描器测试。"""
from __future__ import annotations

from pathlib import Path

from wechat_sweeper.detector import (
    ALL_CATEGORIES,
    CATEGORY_ATTACH,
    CATEGORY_CACHE,
    CATEGORY_FILE,
    CATEGORY_IMAGE,
    CATEGORY_VIDEO,
    detect_accounts,
)
from wechat_sweeper.scanner import ScanOptions, aggregate, scan_accounts


def _scan(fake_wechat_root, days=365, cats=None):
    accounts = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False
    )
    opts = ScanOptions(categories=cats or tuple(ALL_CATEGORIES), days=days)
    results = scan_accounts(accounts, opts)
    return accounts, results


def test_age_filter_excludes_recent(fake_wechat_root: Path):
    _, results = _scan(fake_wechat_root, days=365)
    # 不应包含 NEW 文件（today.zip / recent.mp4 / fresh.jpg）
    names = {f.path.name for r in results for f in r.files}
    assert "today.zip" not in names
    assert "recent.mp4" not in names
    assert "fresh.jpg" not in names


def test_age_filter_includes_old(fake_wechat_root: Path):
    _, results = _scan(fake_wechat_root, days=365)
    names = {f.path.name for r in results for f in r.files}
    assert "report.pdf" in names
    assert "meeting.mp4" in names
    assert "photo.jpg" in names


def test_days_zero_includes_all(fake_wechat_root: Path):
    _, results = _scan(fake_wechat_root, days=0)
    names = {f.path.name for r in results for f in r.files}
    assert "today.zip" in names   # 新文件也应纳入
    assert "report.pdf" in names


def test_size_totals(fake_wechat_root: Path):
    accounts, results = _scan(fake_wechat_root, days=365)
    agg = aggregate(results)
    # 个人微信旧: 2+15+3+0.5+1 = 21.5 MB ; 企业微信旧: 3+20+2+0.75+1 = 26.75 MB
    expected = (2 + 15 + 3 + 0.5 + 1 + 3 + 20 + 2 + 0.75 + 1) * 1024 * 1024
    assert agg["total_size"] == expected
    assert agg["account_count"] == 2


def test_category_filter(fake_wechat_root: Path):
    accounts, results = _scan(fake_wechat_root, days=365, cats=(CATEGORY_VIDEO,))
    cats_found = {f.category for r in results for f in r.files}
    assert cats_found == {CATEGORY_VIDEO}
    # 只有 video：个人微信 meeting.mp4(15) + 企业微信 training.mp4(20) = 35 MB
    agg = aggregate(results)
    assert agg["total_size"] == (15 + 20) * 1024 * 1024


def test_message_db_never_scanned(fake_wechat_root: Path):
    _, results = _scan(fake_wechat_root, days=0)
    names = {f.path.name for r in results for f in r.files}
    assert "chat.db" not in names


def test_size_by_category(fake_wechat_root: Path):
    accounts, results = _scan(fake_wechat_root, days=365)
    agg = aggregate(results)
    sbc = agg["size_by_category"]
    # image: 个人 photo.jpg(3) + 企业 banner.png(2) = 5 MB
    assert sbc[CATEGORY_IMAGE] == 5 * 1024 * 1024
    # file 类别(File 目录): report.pdf(2) + contract.pdf(3) = 5 MB
    assert sbc[CATEGORY_FILE] == 5 * 1024 * 1024
    # attach 类别(Attach 目录): doc.xlsx(1) + spec.docx(1) = 2 MB
    assert sbc[CATEGORY_ATTACH] == 2 * 1024 * 1024
    # video: meeting.mp4(15) + training.mp4(20) = 35 MB
    assert sbc[CATEGORY_VIDEO] == 35 * 1024 * 1024


def test_min_size_filter(fake_wechat_root: Path):
    accounts = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False
    )
    opts = ScanOptions(categories=tuple(ALL_CATEGORIES), days=365, min_size=10 * 1024 * 1024)
    results = scan_accounts(accounts, opts)
    for r in results:
        for f in r.files:
            assert f.size >= 10 * 1024 * 1024
