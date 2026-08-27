import csv
from pathlib import Path
from typing import Callable

from docx import Document
from openpyxl import load_workbook
from pypdf import PdfReader


TEXT_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}
SPREADSHEET_SUFFIXES = {".xlsx", ".xlsm", ".csv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_SUFFIXES = TEXT_SUFFIXES | SPREADSHEET_SUFFIXES | IMAGE_SUFFIXES
MAX_SHEETS = 10
MAX_ROWS_PER_SHEET = 200
MAX_COLUMNS_PER_SHEET = 30


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).replace("\r", " ").replace("\n", " ").strip()


def _table_to_text(name: str, rows: list[list[str]], truncated: bool) -> str:
    non_empty_rows = [row for row in rows if any(row)]
    if not non_empty_rows:
        return ""
    lines = [f"## 工作表：{name}"]
    for row in non_empty_rows:
        lines.append(" | ".join(row))
    if truncated:
        lines.append("[该工作表内容过长，已截取前 200 行和前 30 列]")
    return "\n".join(lines)


def _extract_workbook(path: Path) -> str:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sections = []
    for sheet_index, worksheet in enumerate(workbook.worksheets[:MAX_SHEETS]):
        rows = []
        for row in worksheet.iter_rows(max_row=MAX_ROWS_PER_SHEET, max_col=MAX_COLUMNS_PER_SHEET, values_only=True):
            rows.append([_cell_text(value) for value in row])
        truncated = worksheet.max_row > MAX_ROWS_PER_SHEET or worksheet.max_column > MAX_COLUMNS_PER_SHEET
        section = _table_to_text(worksheet.title, rows, truncated)
        if section:
            sections.append(section)
    if len(workbook.worksheets) > MAX_SHEETS:
        sections.append("[工作簿工作表超过 10 个，已只读取前 10 个]")
    return "\n\n".join(sections)


def _extract_csv(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as file:
        rows = [[_cell_text(value) for value in row[:MAX_COLUMNS_PER_SHEET]] for row in list(csv.reader(file))[:MAX_ROWS_PER_SHEET]]
    return _table_to_text(path.stem, rows, False)


def extract_text(path: Path, image_to_text: Callable[[Path], str] | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("仅支持 PDF、DOCX、TXT、Markdown、XLSX、XLSM、CSV 或图片文件")
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".xlsx", ".xlsm"}:
        return _extract_workbook(path)
    if suffix == ".csv":
        return _extract_csv(path)
    if suffix in IMAGE_SUFFIXES:
        if image_to_text is None:
            raise ValueError("图片资料需要配置可用的多模态文本模型，才能提取图片中的文字和画面信息")
        return image_to_text(path)
    if suffix == ".docx":
        document = Document(path)
        return "\n\n".join(p.text.strip() for p in document.paragraphs if p.text.strip())

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)


def merge_materials(paths: list[Path], limit: int = 60_000, image_to_text: Callable[[Path], str] | None = None) -> str:
    pieces = []
    for path in paths:
        text = extract_text(path, image_to_text=image_to_text).strip()
        if text:
            pieces.append(f"# 资料：{path.name}\n\n{text}")
    merged = "\n\n---\n\n".join(pieces)
    if not merged:
        raise ValueError("未能从上传资料中提取到文本")
    return merged[:limit]
