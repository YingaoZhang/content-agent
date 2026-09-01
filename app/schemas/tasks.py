from datetime import datetime

from pydantic import BaseModel, Field


class TaskSummary(BaseModel):
    job_id: str
    status: str
    title: str
    topic: str
    objective: str
    theme: str
    parent_job_id: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskDetail(TaskSummary):
    request: dict = Field(default_factory=dict)
    outline: str = ""
    markdown_url: str | None = None
    html_url: str | None = None
    preview_url: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
