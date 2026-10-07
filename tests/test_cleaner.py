"""清理器测试：dry-run 安全、回收站删除、边界校验。"""
from __future__ import annotations

from pathlib import Path

from wechat_sweeper.cleaner import CleanOptions, clean_scan
from wechat_sweeper.detector import ALL_CATEGORIES, detect_accounts
from wechat_sweeper.scanner import ScanOptions, scan_accounts


def _setup(fake_wechat_root: Path, days=365):
    accounts = detect_accounts(
        extra_roots=[fake_wechat_root], include_platform_roots=False
    )
    opts = ScanOptions(categories=tuple(ALL_CATEGORIES), days=days)
    results = scan_accounts(accounts, opts)
    return accounts, results


def test_dry_run_does_not_delete(fake_wechat_root: Path):
    accounts, results = _setup(fake_wechat_root)
    paths_before = {f.path for r in results for f in r.files}
    report = clean_scan(results, accounts, CleanOptions(dry_run=True))
    assert report.dry_run is True
    assert all(o.action == "dry-run" for o in report.outcomes)
    assert report.freed_bytes == sum(f.size for r in results for f in r.files)
    # 文件仍在
    for p in paths_before:
        assert p.exists(), f"{p} 应仍然存在（dry-run 不删除）"


def test_trash_removes_files(fake_wechat_root: Path, tmp_path: Path, monkeypatch):
    """验证"移入回收站"路径的接线逻辑。

    用 monkeypatch 替换 send2trash，把文件移到一个临时回收站目录，
    避免依赖 macOS 在沙盒临时目录下对系统回收站的权限限制。
    """
    trash_dir = tmp_path / "Trash"
    trash_dir.mkdir()

    def fake_send2trash(paths):
        if isinstance(paths, (str, bytes)):
            paths = [paths]
        for p in paths:
            src = Path(p)
            dst = trash_dir / src.name
            src.replace(dst)

    monkeypatch.setattr("wechat_sweeper.cleaner.send2trash", fake_send2trash)

    accounts, results = _setup(fake_wechat_root)
    paths_before = {f.path for r in results for f in r.files}
    report = clean_scan(results, accounts, CleanOptions(permanent=False, dry_run=False))
    assert report.dry_run is False
    assert report.trashed > 0
    assert report.deleted == 0
    assert report.freed_bytes == sum(f.size for r in results for f in r.files)
    # 原位置文件已移走
    for p in paths_before:
        assert not p.exists(), f"{p} 应已从原位置移走"
    # 且在回收站目录中能找到对应文件
    assert any(trash_dir.iterdir())


def test_permanent_delete(fake_wechat_root: Path):
    accounts, results = _setup(fake_wechat_root)
    paths_before = {f.path for r in results for f in r.files}
    report = clean_scan(results, accounts, CleanOptions(permanent=True, dry_run=False))
    assert report.deleted > 0
    assert report.trashed == 0
    for p in paths_before:
        assert not p.exists()


def test_confirm_abort_skips(fake_wechat_root: Path):
    accounts, results = _setup(fake_wechat_root)
    paths_before = {f.path for r in results for f in r.files}
    report = clean_scan(
        results, accounts,
        CleanOptions(confirm=lambda count, b: False),
    )
    assert report.skipped == report.total_files
    assert report.freed_bytes == 0
    for p in paths_before:
        assert p.exists()


def test_empty_results(fake_wechat_root: Path):
    accounts, results = _setup(fake_wechat_root, days=99999)  # 没有更老的文件
    # days=99999: file_mtime + 99999*86400 <= now ⟺ now - mtime >= 99999 days → 无
    report = clean_scan(results, accounts, CleanOptions())
    assert report.total_files == 0
    assert report.freed_bytes == 0


def test_no_outside_escape(fake_wechat_root: Path, tmp_path: Path):
    """伪造一个路径在缓存目录外的文件，应被跳过。"""
    accounts, results = _setup(fake_wechat_root)
    # 注入一个外部文件条目
    from wechat_sweeper.scanner import FileEntry
    outside = tmp_path / "outside.txt"
    outside.write_text("haha")
    results[0].files.append(
        FileEntry(path=outside, size=4, mtime=0,
                  category="file", ext_category="file",
                  account_id=results[0].account.account_id)
    )
    report = clean_scan(results, accounts, CleanOptions())
    assert report.skipped >= 1
    assert outside.exists(), "缓存目录外的文件不应被删除"
