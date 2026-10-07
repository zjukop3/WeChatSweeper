"""配置持久化测试。"""
from __future__ import annotations

from pathlib import Path

from wechat_sweeper.config import Config, Settings


def test_roundtrip(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    cfg = Config(cfg_path)
    s = Settings(days=180, categories=["video", "image"], use_trash=False,
                 custom_roots=["/tmp/wx"])
    cfg.save(s)
    loaded = cfg.load()
    assert loaded.days == 180
    assert loaded.categories == ["video", "image"]
    assert loaded.use_trash is False
    assert loaded.custom_roots == ["/tmp/wx"]


def test_defaults_when_missing(tmp_path: Path):
    cfg = Config(tmp_path / "nope.json")
    s = cfg.load()
    assert s.days == 365
    assert s.use_trash is True


def test_invalid_json_falls_back(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    cfg = Config(p)
    assert cfg.load().days == 365  # 默认


def test_reset(tmp_path: Path):
    p = tmp_path / "config.json"
    cfg = Config(p)
    cfg.save(Settings(days=99))
    assert p.exists()
    cfg.reset()
    assert not p.exists()
