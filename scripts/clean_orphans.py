"""孤儿上传文件清理：删除 data/uploads 下数据库已无对应文档记录的文件。

适用场景：文档删除时本地文件清理失败、手动拷贝文件进上传目录、开发调试残留等，
导致磁盘上残留不再被引用的上传文件。

用法：
    .venv\\Scripts\\python.exe scripts/clean_orphans.py            # 正式删除
    .venv\\Scripts\\python.exe scripts/clean_orphans.py --dry-run  # 仅列出，不删除
    .venv\\Scripts\\python.exe scripts/clean_orphans.py --upload-dir data/local/uploads
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.core.config import load_settings, override_settings  # noqa: E402
from app.db.models import Document  # noqa: E402
from app.db.session import get_session_factory, init_engine  # noqa: E402


def collect_orphans(upload_root: Path, known_paths: set[Path]) -> list[Path]:
    """遍历上传目录，返回不在 known_paths 中的文件列表。"""
    orphans: list[Path] = []
    if not upload_root.exists():
        return orphans
    for path in upload_root.rglob("*"):
        if path.is_file():
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved not in known_paths:
                orphans.append(path)
    return orphans


def prune_empty_dirs(upload_root: Path, dry_run: bool) -> int:
    """自底向上删除空目录，返回删除的目录数。

    dry_run 模式下不真正删除，但会模拟已删除的子目录，
    保证报告结果与正式执行一致（父级空目录同样会被报告）。
    """
    removed = 0
    if not upload_root.exists():
        return removed
    virtual_removed: set[Path] = set()
    for path in sorted(upload_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_dir():
            continue
        children = list(path.iterdir())
        is_empty = not children or all(child in virtual_removed for child in children)
        if not is_empty:
            continue
        if dry_run:
            print(f"  [空目录] {path}")
        else:
            try:
                path.rmdir()
                print(f"  已删除空目录：{path}")
            except OSError as exc:
                print(f"  删除空目录失败：{path} -> {exc}")
                continue
        virtual_removed.add(path)
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="清理数据库已无记录的上传文件")
    parser.add_argument("--dry-run", action="store_true", help="仅列出孤儿文件，不实际删除")
    parser.add_argument("--upload-dir", default="", help="覆盖上传目录（默认取 config.yaml 的 app.upload_dir）")
    args = parser.parse_args()

    cfg = load_settings(PROJECT_ROOT / "config.yaml")
    if args.upload_dir:
        cfg.app.upload_dir = args.upload_dir
    override_settings(cfg)
    init_engine(cfg, force=True)

    upload_root = cfg.upload_path
    print(f"上传目录：{upload_root}")

    db = get_session_factory()()
    try:
        stored = db.scalars(select(Document.stored_path)).all()
    finally:
        db.close()

    known_paths: set[Path] = set()
    for raw in stored:
        if not raw:
            continue
        try:
            known_paths.add(Path(raw).resolve())
        except OSError:
            continue
    print(f"数据库中记录的文档文件数：{len(known_paths)}")

    orphans = collect_orphans(upload_root, known_paths)
    if not orphans:
        print("未发现孤儿文件，上传目录干净。")
        prune_empty_dirs(upload_root, args.dry_run)
        return 0

    total_size = 0
    for path in orphans:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        total_size += size
        if args.dry_run:
            print(f"  [孤儿] {path}（{size / 1024:.1f} KB）")
        else:
            try:
                path.unlink()
                print(f"  已删除：{path}（{size / 1024:.1f} KB）")
            except OSError as exc:
                print(f"  删除失败：{path} -> {exc}")

    action = "待删除" if args.dry_run else "已删除"
    print(f"{action}孤儿文件 {len(orphans)} 个，合计 {total_size / 1024 / 1024:.2f} MB")
    prune_empty_dirs(upload_root, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
