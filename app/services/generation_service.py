"""Generation job lifecycle and background-execution entry points.

This module owns durable job inputs, state transitions, and dispatch. Platform
content generation stays in ``app.workflow`` and ``app.channels``.
"""

import json
import re
import shutil
import uuid
from pathlib import Path

from ..channels import get_channel
from ..config import settings
from ..forbidden_words import forbidden_words_warning
from ..harness import ContentModelHarness
from ..schemas import ContentRequest, Platform
from ..workflow import (
    WorkflowState,
    build_brief,
    build_graph,
    build_revision_graph,
    generate_candidate_outlines,
    generate_titles,
    validate_project,
)


def _create_job_dir(storage_dir: Path) -> tuple[str, Path]:
    job_id = uuid.uuid4().hex[:12]
    job_dir = storage_dir / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    return job_id, job_dir


def _load_metadata(job_dir: Path) -> dict:
    try:
        return json.loads((job_dir / "run.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_run_metadata(
    job_dir: Path,
    request: ContentRequest,
    harness: ContentModelHarness,
    parent_job_id: str | None = None,
    stage: str = "completed",
    warnings: list[str] | None = None,
    extra: dict | None = None,
) -> None:
    metadata = _load_metadata(job_dir)
    metadata.update(
        {
            "request": request.model_dump(mode="json"),
            "text_api": {"base_url": settings.text_base_url, "model": settings.text_model},
            "image_api": {"base_url": settings.image_base_url, "model": settings.image_model},
            "trace": harness.trace,
            "stage": stage,
        }
    )
    if parent_job_id:
        metadata["parent_job_id"] = parent_job_id
    if warnings:
        metadata["warnings"] = warnings
    if extra:
        metadata.update(extra)
    (job_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _reference_images(job_dir: Path) -> list[Path]:
    references_dir = job_dir / "references"
    if not references_dir.exists():
        return []
    return sorted(references_dir.iterdir(), key=lambda path: path.name)


def reserve_job(
    request: ContentRequest,
    material_text: str,
    storage_dir: Path,
    reference_images: list[Path] | None = None,
    *,
    parent_job_id: str | None = None,
    kind: str = "generate",
) -> str:
    """Persist a job's inputs and mark it pending for background execution."""
    job_id, job_dir = _create_job_dir(storage_dir)
    (job_dir / "source_material.md").write_text(material_text, encoding="utf-8")
    if request.platform == Platform.XIAOHONGSHU and reference_images:
        references_dir = job_dir / "references"
        references_dir.mkdir(exist_ok=True)
        for index, source_path in enumerate(reference_images, start=1):
            shutil.copy2(source_path, references_dir / f"{index:02d}-{source_path.name}")
    metadata = {
        "request": request.model_dump(mode="json"),
        "stage": "pending",
        "kind": kind,
    }
    if parent_job_id:
        metadata["parent_job_id"] = parent_job_id
    (job_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return job_id


def prepare_outline(request: ContentRequest, material_text: str, storage_dir: Path) -> str:
    return reserve_job(request, material_text, storage_dir, kind="titles")


def prepare_generation(
    request: ContentRequest,
    material_text: str,
    storage_dir: Path,
    reference_images: list[Path] | None = None,
) -> str:
    return reserve_job(request, material_text, storage_dir, reference_images, kind="generate")


def prepare_revision(parent_job_id: str, feedback: str, storage_dir: Path) -> str:
    feedback = (feedback or "").strip()
    if not feedback:
        raise ValueError("请说明希望如何修改当前成品")
    parent_dir = storage_dir / "jobs" / parent_job_id
    source_path = parent_dir / "source_material.md"
    article_path = parent_dir / "article.md"
    metadata_path = parent_dir / "run.json"
    if not source_path.exists() or not article_path.exists() or not metadata_path.exists():
        raise RuntimeError("未找到当前成品的原始资料或版本记录，无法继续修改")

    request = ContentRequest.model_validate(_load_metadata(parent_dir)["request"])
    child_id, child_dir = _create_job_dir(storage_dir)
    (child_dir / "source_material.md").write_text(
        source_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (child_dir / "article_draft.md").write_text(
        article_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    metadata = {
        "request": request.model_dump(mode="json"),
        "stage": "pending",
        "kind": "revision",
        "parent_job_id": parent_job_id,
        "feedback": feedback,
    }
    (child_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return child_id


def select_title(job_id: str, title: str, storage_dir: Path) -> None:
    """Record the selected title and queue candidate-outline generation."""
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise FileNotFoundError(job_id)
    title = title.strip()
    if not title:
        raise ValueError("请选择一个候选标题")
    if len(title) > 120:
        raise ValueError("标题过长，请控制在 120 个字符以内")

    job_dir = storage_dir / "jobs" / job_id
    if not (job_dir / "source_material.md").exists() or not (job_dir / "run.json").exists():
        raise RuntimeError("未找到候选标题对应的原始资料或任务记录")
    if (job_dir / "article.md").exists():
        raise ValueError("该任务已经生成过成品；请在成品下方继续修改文章")

    metadata = _load_metadata(job_dir)
    metadata["selected_title"] = title
    metadata["kind"] = "outlines"
    metadata["stage"] = "pending"
    metadata.pop("error", None)
    (job_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def accept_outline(job_id: str, outline: str, storage_dir: Path, title: str | None = None) -> None:
    """Validate the selected outline and queue final generation."""
    if not re.fullmatch(r"[a-f0-9]{12}", job_id):
        raise FileNotFoundError(job_id)
    outline = outline.strip()
    if len(outline) < 20:
        raise ValueError("请保留至少一条有实际内容的大纲要点")
    if len(outline) > 12000:
        raise ValueError("大纲过长，请控制在 12000 个字符以内")

    job_dir = storage_dir / "jobs" / job_id
    if not (job_dir / "source_material.md").exists() or not (job_dir / "run.json").exists():
        raise RuntimeError("未找到待确认大纲的原始资料或任务记录")
    if (job_dir / "article.md").exists():
        raise ValueError("该大纲已经生成过成品；请在成品下方继续修改文章")

    metadata = _load_metadata(job_dir)
    if title:
        metadata["selected_title"] = title.strip()
    metadata["kind"] = "generate_from_outline"
    metadata["stage"] = "pending"
    metadata.pop("error", None)
    (job_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (job_dir / "outline.md").write_text(outline, encoding="utf-8")


def execute_job(job_id: str, storage_dir: Path) -> dict:
    """Run the stored pipeline selected by the job kind."""
    kind = _load_metadata(storage_dir / "jobs" / job_id).get("kind", "generate")
    handlers = {
        "titles": run_titles_job,
        "outlines": run_outlines_job,
        "generate_from_outline": run_generation_from_outline_job,
        "revision": run_revision_job,
    }
    return handlers.get(kind, run_generation_job)(job_id, storage_dir)


def mark_job_failed(job_id: str, error: str, storage_dir: Path) -> None:
    job_dir = storage_dir / "jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    metadata = _load_metadata(job_dir)
    metadata["stage"] = "failed"
    metadata["error"] = error
    (job_dir / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_job(job_id: str, storage_dir: Path) -> tuple[Path, dict, ContentRequest, str]:
    job_dir = storage_dir / "jobs" / job_id
    metadata = _load_metadata(job_dir)
    request = ContentRequest.model_validate(metadata["request"])
    material_text = (job_dir / "source_material.md").read_text(encoding="utf-8")
    return job_dir, metadata, request, material_text


def run_titles_job(job_id: str, storage_dir: Path) -> dict:
    job_dir, _, request, material_text = _load_job(job_id, storage_dir)
    harness = ContentModelHarness(enable_image_generation=False)
    state: WorkflowState = {
        "request": request,
        "material_text": material_text,
        "job_dir": str(job_dir),
        "harness": harness,
    }
    validate_project(state)
    state.update(build_brief(state))
    titles = generate_titles(state)
    _write_run_metadata(job_dir, request, harness, stage="titles_ready", extra={"titles": titles})
    return {"job_id": job_id, "titles": titles}


def run_outlines_job(job_id: str, storage_dir: Path) -> dict:
    job_dir, metadata, request, material_text = _load_job(job_id, storage_dir)
    harness = ContentModelHarness(enable_image_generation=False)
    state: WorkflowState = {
        "request": request,
        "material_text": material_text,
        "job_dir": str(job_dir),
        "harness": harness,
        "title": metadata.get("selected_title", request.topic),
    }
    validate_project(state)
    state.update(build_brief(state))
    outlines = generate_candidate_outlines(state)
    _write_run_metadata(
        job_dir, request, harness, stage="outline_ready", extra={"outlines": outlines}
    )
    return {"job_id": job_id, "outlines": outlines}


def run_generation_job(job_id: str, storage_dir: Path) -> dict:
    job_dir, _, request, material_text = _load_job(job_id, storage_dir)
    validate_project({"request": request, "material_text": material_text})
    harness = ContentModelHarness(
        enable_image_generation=request.image_count > 0 and request.platform != Platform.XIAOHONGSHU
    )
    final = get_channel(request.platform).generate(
        request, material_text, job_dir, harness, _reference_images(job_dir)
    )
    warnings = list(final.get("warnings", []))
    _write_run_metadata(job_dir, request, harness, warnings=warnings)
    return {
        "job_id": job_id,
        "image_plan": final.get("image_plan", final.get("cards", [])),
        "warnings": warnings,
    }


def run_generation_from_outline_job(job_id: str, storage_dir: Path) -> dict:
    job_dir, metadata, request, material_text = _load_job(job_id, storage_dir)
    outline_path = job_dir / "outline.md"
    if not outline_path.exists():
        raise RuntimeError("未找到待确认大纲的原始资料或任务记录")
    harness = ContentModelHarness(enable_image_generation=request.image_count > 0)
    final = build_graph().invoke(
        {
            "request": request,
            "material_text": material_text,
            "job_dir": str(job_dir),
            "harness": harness,
            "title": metadata.get("selected_title"),
            "outline": outline_path.read_text(encoding="utf-8"),
        }
    )
    warnings = list(final.get("warnings", []))
    if warning := forbidden_words_warning(final.get("article", "")):
        warnings.append(warning)
    _write_run_metadata(job_dir, request, harness, warnings=warnings)
    return {"job_id": job_id, "image_plan": final["image_plan"], "warnings": warnings}


def run_revision_job(job_id: str, storage_dir: Path) -> dict:
    job_dir, metadata, request, material_text = _load_job(job_id, storage_dir)
    article = (job_dir / "article_draft.md").read_text(encoding="utf-8")
    harness = ContentModelHarness(enable_image_generation=request.image_count > 0)
    final = build_revision_graph().invoke(
        {
            "request": request,
            "material_text": material_text,
            "article": article,
            "feedback": metadata.get("feedback", ""),
            "job_dir": str(job_dir),
            "harness": harness,
        }
    )
    warnings = list(final.get("warnings", []))
    if warning := forbidden_words_warning(final.get("article", "")):
        warnings.append(warning)
    _write_run_metadata(
        job_dir,
        request,
        harness,
        parent_job_id=metadata.get("parent_job_id"),
        warnings=warnings,
    )
    return {"job_id": job_id, "image_plan": final["image_plan"], "warnings": warnings}


def run_revision(parent_job_id: str, feedback: str, storage_dir: Path | None = None) -> dict:
    """Synchronous convenience entry point used by direct callers and tests."""
    resolved_storage = storage_dir or settings.storage_dir
    revision_id = prepare_revision(parent_job_id, feedback, resolved_storage)
    return run_revision_job(revision_id, resolved_storage)
