from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from ..audiences import AUDIENCE_LABELS, get_audience_profile


class Audience(str, Enum):
    BRAND_PM = "brand_pm"
    RD_FORMULATOR = "rd_formulator"
    PROCUREMENT_REGULATORY_QUALITY = "procurement_regulatory_quality"
    SALES_CHANNEL = "sales_channel"
    PARTNER = "partner"
    INVESTOR = "investor"
    SCIENTIST_EXPERT = "scientist_expert"
    CONSUMER = "consumer"


class FactPolicy(str, Enum):
    MATERIALS_ONLY = "materials_only"
    MATERIALS_AND_COMMON_KNOWLEDGE = "materials_and_common_knowledge"


class Platform(str, Enum):
    WECHAT = "wechat"
    XIAOHONGSHU = "xiaohongshu"


class ContentRequest(BaseModel):
    platform: Platform = Platform.WECHAT
    topic: str = Field(min_length=3, max_length=120)
    # Kept as a string so adding a new JSON profile does not require a code release.
    primary_audience: str
    objective: str = Field(min_length=3, max_length=300)
    call_to_action: str = Field(default="了解更多", min_length=2, max_length=100)
    key_points: str = Field(default="", max_length=500)
    author_name: str = Field(default="{{作者名}}", max_length=80)
    author_bio: str = Field(default="{{一句话简介}}", max_length=160)
    image_count: int = Field(default=3, ge=0, le=10)
    theme: str = Field(default="石墨极简风")
    xhs_layout: str = Field(default="实拍故事", max_length=40)
    target_length: int | None = Field(default=None, ge=800, le=20000)
    caption_length: int | None = Field(default=None, ge=100, le=2000)
    fact_policy: FactPolicy = FactPolicy.MATERIALS_ONLY

    @model_validator(mode="after")
    def validate_platform_options(self):
        try:
            get_audience_profile(self.primary_audience)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        if self.platform == Platform.XIAOHONGSHU and not 1 <= self.image_count <= 10:
            raise ValueError("小红书图文至少需要 1 张卡片，最多 10 张")
        if self.platform == Platform.WECHAT and self.image_count > 9:
            raise ValueError("公众号文章最多支持 9 张图片")
        return self

    @field_validator(
        "topic",
        "objective",
        "call_to_action",
        "key_points",
        "author_name",
        "author_bio",
    )
    @classmethod
    def clean_text(cls, value: str) -> str:
        return value.strip()


class ImagePlanItem(BaseModel):
    filename: str
    placement: str
    alt: str
    prompt: str
    insert_after_heading: str = ""
    visual_focus: str = ""
    size: str = ""
    quality: str = ""


class XiaohongshuCard(BaseModel):
    filename: str
    role: str = Field(default="content", pattern="^(cover|content|closing)$")
    image_source: str = Field(default="uploaded_photo", pattern="^(uploaded_photo|ai_illustration)$")
    source_photo_index: int | None = Field(default=None, ge=1)
    headline: str = Field(min_length=2, max_length=34)
    body: str = Field(min_length=2, max_length=160)
    visual_focus: str = Field(min_length=2, max_length=160)
    # Only used when image_source is ai_illustration.
    prompt: str = ""


class GenerationResult(BaseModel):
    job_id: str
    title: str
    markdown_url: str
    html_url: str
    preview_url: str
    image_urls: list[str]
    images_zip_url: str | None = None
    warnings: list[str] = Field(default_factory=list)
    platform: Platform = Platform.WECHAT
    caption_url: str | None = None
    card_plan_url: str | None = None


class OutlineResult(BaseModel):
    job_id: str
    outline: str


class JobAccepted(BaseModel):
    job_id: str
    status: str = "pending"
