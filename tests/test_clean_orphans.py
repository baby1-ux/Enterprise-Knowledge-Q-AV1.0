"""孤儿上传文件清理脚本测试（scripts/clean_orphans.py 的纯函数部分）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "clean_orphans.py"


def _load_script_module():
    """从文件路径加载脚本模块（scripts 目录不是 Python 包）。"""
    spec = importlib.util.spec_from_file_location("clean_orphans_under_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def script_module():
    """加载被测试的脚本模块，用完后从 sys.modules 移除。"""
    module = _load_script_module()
    yield module
    sys.modules.pop("clean_orphans_under_test", None)


def test_collect_orphans_finds_unrecorded_files(script_module, tmp_path: Path) -> None:
    """数据库无记录的文件被识别为孤儿，有记录的保留。"""
    upload_root = tmp_path / "uploads"
    (upload_root / "1" / "10").mkdir(parents=True)
    orphan = upload_root / "1" / "10" / "orphan.md"
    orphan.write_text("孤儿文件", encoding="utf-8")
    known = upload_root / "1" / "10" / "known.md"
    known.write_text("已记录文件", encoding="utf-8")

    orphans = script_module.collect_orphans(upload_root, {known.resolve()})
    assert orphans == [orphan]


def test_collect_orphans_missing_dir(script_module, tmp_path: Path) -> None:
    """上传目录不存在时返回空列表。"""
    assert script_module.collect_orphans(tmp_path / "not-exist", set()) == []


def test_collect_orphans_clean_dir(script_module, tmp_path: Path) -> None:
    """全部文件都有记录时没有孤儿。"""
    upload_root = tmp_path / "uploads"
    upload_root.mkdir()
    file_path = upload_root / "a.md"
    file_path.write_text("内容", encoding="utf-8")
    assert script_module.collect_orphans(upload_root, {file_path.resolve()}) == []


def test_prune_empty_dirs(script_module, tmp_path: Path) -> None:
    """空目录被自底向上清理，非空目录保留。"""
    upload_root = tmp_path / "uploads"
    (upload_root / "1" / "10" / "20").mkdir(parents=True)
    keep = upload_root / "keep"
    keep.mkdir()
    (keep / "file.md").write_text("内容", encoding="utf-8")

    removed = script_module.prune_empty_dirs(upload_root, dry_run=False)
    assert removed >= 3  # 20、10、1 三级空目录
    assert not (upload_root / "1").exists()
    assert keep.exists()


def test_prune_empty_dirs_dry_run(script_module, tmp_path: Path) -> None:
    """dry_run 模式只报告不删除。"""
    upload_root = tmp_path / "uploads"
    (upload_root / "1" / "10").mkdir(parents=True)

    removed = script_module.prune_empty_dirs(upload_root, dry_run=True)
    assert removed >= 2
    assert (upload_root / "1" / "10").exists()


def test_prune_empty_dirs_missing_root(script_module, tmp_path: Path) -> None:
    """目录不存在时返回 0。"""
    assert script_module.prune_empty_dirs(tmp_path / "not-exist", dry_run=False) == 0
