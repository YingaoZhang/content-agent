"""Audience profile registry backed by independent JSON files."""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


PROFILE_DIR = Path(__file__).with_name("audience_profiles")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class AudienceProfile(BaseModel):
    """Validated, extensible definition of one primary audience."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=2, max_length=64)
    version: int = Field(default=1, ge=1)
    label: str = Field(min_length=1, max_length=80)
    summary: str = Field(default="", max_length=300)
    role: str = Field(default="", max_length=120)
    knowledge_level: str = Field(default="", max_length=80)
    goals: list[str] = Field(default_factory=list, max_length=12)
    pains: list[str] = Field(default_factory=list, max_length=12)
    decision_factors: list[str] = Field(default_factory=list, max_length=12)
    preferred_evidence: list[str] = Field(default_factory=list, max_length=12)
    objections: list[str] = Field(default_factory=list, max_length=12)
    tone: str = Field(min_length=1, max_length=160)
    focus: str = Field(min_length=1, max_length=300)
    structure: str = Field(min_length=1, max_length=160)
    cta_style: str = Field(default="自然、具体、低承诺", max_length=160)
    visual_direction: str = Field(default="", max_length=500)
    prompt_rules: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        value = value.strip()
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("id 只能包含小写字母、数字和下划线，且必须以字母开头")
        return value

    @field_validator(
        "goals", "pains", "decision_factors", "preferred_evidence", "objections", "prompt_rules"
    )
    @classmethod
    def clean_list(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if isinstance(item, str) and item.strip()]
        if len(cleaned) != len(values):
            raise ValueError("列表字段只能包含非空字符串")
        return cleaned

    def strategy(self) -> dict[str, Any]:
        """Return the compact strategy consumed by existing prompt builders."""
        strategy = {
            "tone": self.tone,
            "focus": self.focus,
            "structure": self.structure,
            "summary": self.summary,
            "role": self.role,
            "knowledge_level": self.knowledge_level,
            "goals": self.goals,
            "pains": self.pains,
            "decision_factors": self.decision_factors,
            "preferred_evidence": self.preferred_evidence,
            "objections": self.objections,
            "cta_style": self.cta_style,
            "prompt_rules": self.prompt_rules,
        }
        # Preserve newly added JSON fields in the model-facing context without
        # requiring a Python release for every profile iteration.
        if self.model_extra:
            strategy["additional_fields"] = self.model_extra
        return strategy


def load_audience_profiles(directory: Path = PROFILE_DIR) -> dict[str, AudienceProfile]:
    """Load and validate all profile files from an independent directory."""
    if not directory.exists():
        raise RuntimeError(f"用户画像目录不存在：{directory}")
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise RuntimeError(f"用户画像目录为空：{directory}")

    profiles: dict[str, AudienceProfile] = {}
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            profile = AudienceProfile.model_validate(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(f"用户画像文件校验失败：{path.name}：{exc}") from exc
        if profile.id != path.stem:
            raise RuntimeError(f"用户画像文件名必须与 id 一致：{path.name} -> {profile.id}")
        if profile.id in profiles:
            raise RuntimeError(f"用户画像 id 重复：{profile.id}")
        profiles[profile.id] = profile
    return profiles


AUDIENCE_PROFILES = load_audience_profiles()
AUDIENCE_STRATEGIES = {profile_id: profile.strategy() for profile_id, profile in AUDIENCE_PROFILES.items()}
AUDIENCE_LABELS = {profile_id: profile.label for profile_id, profile in AUDIENCE_PROFILES.items()}


def get_audience_profile(audience: str) -> AudienceProfile:
    audience_id = audience.value if hasattr(audience, "value") else str(audience)
    try:
        return AUDIENCE_PROFILES[audience_id]
    except KeyError as exc:
        raise ValueError(f"未找到用户画像：{audience}") from exc
