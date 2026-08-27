from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Audience(str, Enum):
    BRAND_PM = "brand_pm"
    RD_FORMULATOR = "rd_formulator"
    PROCUREMENT_REGULATORY_QUALITY = "procurement_regulatory_quality"
    SALES_CHANNEL = "sales_channel"
    PARTNER = "partner"
    INVESTOR = "investor"
    SCIENTIST_EXPERT = "scientist_expert"
    CONSUMER = "consumer"


AUDIENCE_LABELS = {
    Audience.BRAND_PM: "品牌方产品经理",
    Audience.RD_FORMULATOR: "研发/配方师",
    Audience.PROCUREMENT_REGULATORY_QUALITY: "采购/法规/质量",
    Audience.SALES_CHANNEL: "销售/渠道/经销商",
    Audience.PARTNER: "合作伙伴",
    Audience.INVESTOR: "投资人",
    Audience.SCIENTIST_EXPERT: "科学家/专家",
    Audience.CONSUMER: "消费者（C端）",
}


class ContentRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=120)
    primary_audience: Audience
    objective: str = Field(min_length=3, max_length=300)
    call_to_action: str = Field(default="了解更多", min_length=2, max_length=100)
    brand_name: str = Field(default="", max_length=80)
    author_name: str = Field(default="{{作者名}}", max_length=80)
    author_bio: str = Field(default="{{一句话简介}}", max_length=160)
    image_count: int = Field(default=3, ge=1, le=5)
    theme: str = Field(default="石墨极简风")

    @field_validator("topic", "objective", "call_to_action", "brand_name", "author_name", "author_bio")
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


class GenerationResult(BaseModel):
    job_id: str
    title: str
    markdown_url: str
    html_url: str
    preview_url: str
    image_urls: list[str]
    warnings: list[str] = []
