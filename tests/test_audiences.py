import json

import pytest
from pydantic import ValidationError

from app.audiences import AUDIENCE_PROFILES, AudienceProfile, load_audience_profiles
from app.schemas import ContentRequest


def test_all_eight_profiles_are_independently_loaded_and_extensible():
    assert len(AUDIENCE_PROFILES) == 8
    profile = AudienceProfile.model_validate(
        {
            "id": "new_reader",
            "label": "新读者",
            "tone": "清晰",
            "focus": "入门",
            "structure": "问题-解释-行动",
            "custom_dimension": "可后续新增",
        }
    )
    assert profile.model_extra == {"custom_dimension": "可后续新增"}
    assert profile.strategy()["additional_fields"]["custom_dimension"] == "可后续新增"


def test_profile_filename_id_and_request_audience_are_validated(tmp_path):
    (tmp_path / "wrong_name.json").write_text(
        json.dumps({"id": "actual_id", "label": "x", "tone": "x", "focus": "x", "structure": "x"}),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="文件名必须与 id 一致"):
        load_audience_profiles(tmp_path)

    with pytest.raises(ValidationError):
        ContentRequest(topic="主题", primary_audience="missing", objective="目标")
