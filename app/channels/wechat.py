"""WeChat long-form generation behind the shared channel interface."""

from pathlib import Path

from ..forbidden_words import forbidden_words_warning
from ..harness import ContentModelHarness
from ..schemas import ContentRequest, Platform
from ..workflow import build_graph


class WechatChannel:
    platform = Platform.WECHAT

    def generate(
        self,
        request: ContentRequest,
        material_text: str,
        job_dir: Path,
        harness: ContentModelHarness,
        reference_images: list[Path],
    ) -> dict:
        final = build_graph().invoke(
            {
                "request": request,
                "material_text": material_text,
                "job_dir": str(job_dir),
                "harness": harness,
            }
        )
        warnings = list(final.get("warnings", []))
        if warning := forbidden_words_warning(final.get("article", "")):
            warnings.append(warning)
        return {"image_plan": final["image_plan"], "warnings": warnings}
