from pathlib import Path

import pytest
from openpyxl import Workbook

from app.materials import extract_text, merge_materials


def test_merge_text_materials(tmp_path: Path):
    first = tmp_path / "a.md"
    second = tmp_path / "b.txt"
    first.write_text("# 产品资料\n核心信息", encoding="utf-8")
    second.write_text("补充材料", encoding="utf-8")
    merged = merge_materials([first, second])
    assert "产品资料" in merged
    assert "补充材料" in merged


def test_extract_excel_material(tmp_path: Path):
    source = tmp_path / "materials.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "产品资料"
    worksheet.append(["产品", "核心卖点"])
    worksheet.append(["原料 A", "保湿"])
    workbook.save(source)

    text = extract_text(source)

    assert "工作表：产品资料" in text
    assert "原料 A | 保湿" in text


def test_extract_image_uses_configured_vision_reader(tmp_path: Path):
    source = tmp_path / "reference.png"
    source.write_bytes(b"placeholder")

    text = extract_text(source, image_to_text=lambda path: f"图片资料：{path.name}，包含产品示意图")

    assert "产品示意图" in text


def test_image_requires_a_multimodal_reader(tmp_path: Path):
    source = tmp_path / "reference.png"
    source.write_bytes(b"placeholder")

    with pytest.raises(ValueError, match="多模态文本模型"):
        extract_text(source)


def test_reject_unknown_file_type(tmp_path: Path):
    source = tmp_path / "input.exe"
    source.write_text("no", encoding="utf-8")
    with pytest.raises(ValueError):
        extract_text(source)
