import base64
import json
import re
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

import httpx
from openai import APIConnectionError, APIStatusError, OpenAI

from .config import settings

T = TypeVar("T")


class ProviderUnavailableError(RuntimeError):
    """A provider failed after all policy-controlled retry attempts."""


def _openai_client(api_key: str, base_url: str) -> OpenAI:
    """Create an OpenAI-compatible client with an explicit proxy policy."""
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=settings.request_timeout_seconds,
        max_retries=0,
        http_client=httpx.Client(
            timeout=settings.request_timeout_seconds,
            trust_env=settings.api_use_system_proxy,
        ),
    )


def _error_status(error: Exception) -> int | None:
    return getattr(error, "status_code", None)


def _retry_after_seconds(error: Exception) -> int:
    response = getattr(error, "response", None)
    header_value = response.headers.get("retry-after") if response is not None else None
    body = getattr(error, "body", None)
    serialized = json.dumps(body, ensure_ascii=False) if isinstance(body, (dict, list)) else str(error)
    match = re.search(r'["\']?retry_after["\']?\s*[:=]\s*["\']?(\d+)', serialized, re.I)
    declared = int(header_value) if header_value and header_value.isdigit() else int(match.group(1)) if match else settings.provider_default_retry_seconds
    return min(max(declared, 1), settings.provider_max_retry_seconds)


def _provider_message(provider_name: str, error: Exception) -> str:
    status = _error_status(error)
    if status in {429, 500, 502, 503, 504}:
        return f"{provider_name} 暂时不可用（HTTP {status}）。请稍后重试。"
    if error.__class__.__name__ == "APITimeoutError":
        return f"{provider_name} 请求超时。请检查网络代理或稍后重试。"
    return f"{provider_name} 调用失败。请检查端点、模型名称和 API 配置。"


def call_with_provider_retry(operation: Callable[[], T], provider_name: str, sleep: Callable[[float], None] = time.sleep) -> T:
    """Retry provider-declared transient errors with a bounded, explicit backoff."""
    for attempt in range(settings.provider_retry_attempts + 1):
        try:
            return operation()
        except (APIStatusError, APIConnectionError) as error:
            status = _error_status(error)
            transient = isinstance(error, APIConnectionError) or status in {429, 500, 502, 503, 504}
            if not transient or attempt >= settings.provider_retry_attempts:
                raise ProviderUnavailableError(_provider_message(provider_name, error)) from error
            sleep(_retry_after_seconds(error))
    raise AssertionError("Retry loop should either return or raise")


class TextApiClient:
    """OpenAI-compatible client for the independently configured text model API."""

    def __init__(self) -> None:
        if not settings.text_api_key:
            raise RuntimeError("缺少 TEXT_API_KEY。请在项目根目录的 .env 中配置后重试。")
        self.client = _openai_client(settings.text_api_key, settings.text_base_url)
        self.trace: list[dict[str, Any]] = []

    def text(self, system: str, user: str, name: str) -> str:
        extra_body = None
        if "dashscope.aliyuncs.com" in settings.text_base_url and settings.text_model.lower().startswith("qwen"):
            extra_body = {"enable_thinking": settings.text_enable_thinking}
        response = call_with_provider_retry(
            lambda: self.client.chat.completions.create(
                model=settings.text_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
                max_tokens=settings.text_max_tokens,
                extra_body=extra_body,
            ),
            "文本 API",
        )
        content = response.choices[0].message.content or ""
        self.trace.append({"node": name, "model": settings.text_model, "kind": "text"})
        return content.strip()

    def json(self, system: str, user: str, name: str) -> dict[str, Any]:
        raw = self.text(system, user + "\n\n只输出合法 JSON，不要 Markdown 代码围栏。", name)
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.S)
        raw = match.group(1) if match else raw
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{name} 未返回可解析 JSON：{raw[:300]}") from exc

class ImageApiClient:
    """OpenAI-compatible client for the independently configured image model API."""

    def __init__(self) -> None:
        if not settings.image_api_key:
            raise RuntimeError("缺少 IMAGE_API_KEY。请在项目根目录的 .env 中配置后重试。")
        self.client = _openai_client(settings.image_api_key, settings.image_base_url)
        self.trace: list[dict[str, Any]] = []

    def image(self, prompt: str, target: Path) -> None:
        response = call_with_provider_retry(
            lambda: self.client.images.generate(
                model=settings.image_model,
                prompt=prompt,
                size="1536x1024",
                quality="medium",
                response_format="b64_json",
            ),
            "图片 API",
        )
        image = response.data[0]
        if getattr(image, "b64_json", None):
            target.write_bytes(base64.b64decode(image.b64_json))
        elif getattr(image, "url", None):
            import urllib.request
            urllib.request.urlretrieve(image.url, target)
        else:
            raise RuntimeError("生图接口未返回图片数据")
        self.trace.append({"node": "generate_images", "model": settings.image_model, "kind": "image", "file": target.name})


class ContentModelHarness:
    """Coordinates independent text and image API clients and exposes one run trace."""

    def __init__(self) -> None:
        self.text_api = TextApiClient()
        self.image_api = ImageApiClient()

    @property
    def trace(self) -> list[dict[str, Any]]:
        return [*self.text_api.trace, *self.image_api.trace]

    def text(self, system: str, user: str, name: str) -> str:
        return self.text_api.text(system, user, name)

    def json(self, system: str, user: str, name: str) -> dict[str, Any]:
        return self.text_api.json(system, user, name)

    def image(self, prompt: str, target: Path) -> None:
        self.image_api.image(prompt, target)
