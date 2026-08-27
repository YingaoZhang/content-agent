from pathlib import Path

from docx import Document
from pypdf import PdfReader


ALLOWED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("仅支持 PDF、DOCX、TXT 或 Markdown 文件")
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".docx":
        document = Document(path)
        return "\n\n".join(p.text.strip() for p in document.paragraphs if p.text.strip())

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages)


def merge_materials(paths: list[Path], limit: int = 60_000) -> str:
    pieces = []
    for path in paths:
        text = extract_text(path).strip()
        if text:
            pieces.append(f"# 资料：{path.name}\n\n{text}")
    merged = "\n\n---\n\n".join(pieces)
    if not merged:
        raise ValueError("未能从上传资料中提取到文本")
    return merged[:limit]

