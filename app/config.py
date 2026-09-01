import warnings
from pathlib import Path

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning
from pydantic_settings import BaseSettings, SettingsConfigDict

# LangGraph emits this from an optional cache module that this demo does not use.
warnings.filterwarnings(
    "ignore",
    category=LangChainPendingDeprecationWarning,
)

ROOT_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    database_url: str = ""
    text_api_key: str = ""
    text_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    text_model: str = "qwen3.7-plus"
    text_enable_thinking: bool = False
    text_max_tokens: int = 7000
    vision_api_key: str = ""
    vision_base_url: str = ""
    vision_model: str = ""
    article_min_chars: int = 4500
    article_target_chars: int = 6500
    image_api_key: str = ""
    image_base_url: str = "https://tokenflux.dev/v1"
    image_model: str = "gpt-image-2"
    request_timeout_seconds: int = 180
    provider_retry_attempts: int = 1
    provider_default_retry_seconds: int = 5
    provider_max_retry_seconds: int = 90
    api_use_system_proxy: bool = True

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def storage_dir(self) -> Path:
        return ROOT_DIR / "storage"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        database_path = (self.storage_dir / "content-agent.db").resolve().as_posix()
        return f"sqlite:///{database_path}"

    @property
    def gzh_skill_dir(self) -> Path:
        return ROOT_DIR / "vendor" / "gzh-design-skill"


settings = Settings()
