from pathlib import Path

import pytest

from app.materials import extract_text, merge_materials


def test_merge_text_materials(tmp_path: Path):
    first = tmp_path / "a.md"
    second = tmp_path / "b.txt"
    first.write_text("# 产品资料\n核心信息", encoding="utf-8")
    second.write_text("补充材料", encoding="utf-8")
    merged = merge_materials([first, second])
    assert "产品资料" in merged
    assert "补充材料" in merged


def test_reject_unknown_file_type(tmp_path: Path):
    source = tmp_path / "input.xlsx"
    source.write_text("no", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_text(source)
