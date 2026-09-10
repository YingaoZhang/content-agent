"""Channel abstraction: each content platform knows how to turn source material into
publishable artifacts. Adding a platform (R2) means adding a module here and registering it.
"""

from pathlib import Path
from typing import Protocol

from ..harness import ContentModelHarness
from ..schemas import ContentRequest, Platform


class Channel(Protocol):
    platform: Platform

    def generate(
        self,
        request: ContentRequest,
        material_text: str,
        job_dir: Path,
        harness: ContentModelHarness,
        reference_images: list[Path],
    ) -> dict:
        """Produce the platform's final artifacts inside ``job_dir``.

        Returns a dict carrying ``warnings`` plus the platform's structured output,
        e.g. ``{"image_plan": [...]}`` or ``{"cards": [...]}``.
        """
        ...
