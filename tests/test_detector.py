"""检测器测试。"""
from __future__ import annotations

from pathlib import Path

from wechat_sweeper.detector import (
    APP_WECOM,
    APP_WECHAT,
    CATEGORY_FILE,
    CATEGORY_VIDEO,
    CATEGORY_IMAGE,
    CATEGORY_CACHE,
    CATEGORY_ATTACH,
    detect_accounts,
    summarize_accounts,
)


def test_detects_both_accounts(fake_wechat_root: Path):
    accounts = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False
    )
    apps = sorted(a.app for a in accounts)
    assert APP_WECHAT in apps
    assert APP_WECOM in apps
    assert len(accounts) == 2


def test_account_cache_dirs(fake_wechat_root: Path):
    accounts = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False
    )
    by_app = {a.app: a for a in accounts}
    wx = by_app[APP_WECHAT]
    cats = {cd.category for cd in wx.cache_dirs}
    assert {CATEGORY_FILE, CATEGORY_VIDEO, CATEGORY_IMAGE, CATEGORY_CACHE, CATEGORY_ATTACH} <= cats
    assert all(cd.exists() for cd in wx.cache_dirs)


def test_message_db_not_treated_as_cache(fake_wechat_root: Path):
    """文字聊天记录库不应被识别为缓存目录。"""
    accounts = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False
    )
    for a in accounts:
        for cd in a.cache_dirs:
            assert "Message" not in str(cd.path)
            assert cd.category in {
                CATEGORY_FILE, CATEGORY_VIDEO, CATEGORY_IMAGE, CATEGORY_CACHE, CATEGORY_ATTACH
            }


def test_app_filter(fake_wechat_root: Path):
    wx_only = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False,
        app_filter=APP_WECHAT,
    )
    assert len(wx_only) == 1
    assert wx_only[0].app == APP_WECHAT


def test_summary(fake_wechat_root: Path):
    accounts = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False
    )
    s = summarize_accounts(accounts)
    assert s["total_accounts"] == 2
    assert s["wechat"] == 1
    assert s["wecom"] == 1
    assert s["cache_dirs"] == sum(len(a.cache_dirs) for a in accounts)


def test_nonexistent_root_safe(tmp_path: Path):
    accounts = detect_accounts(
        extra_roots=[tmp_path / "does-not-exist"], include_platform_roots=False
    )
    assert accounts == []


def test_account_id_derived(fake_wechat_root: Path):
    accounts = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False
    )
    ids = {a.account_id for a in accounts}
    assert "wxid_abc1234567" in ids
    assert "corp_user_001" in ids
