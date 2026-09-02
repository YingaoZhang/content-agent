import base64
import json
import mimetypes
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
    if status == 524:
        return f"{provider_name}上游处理超时（HTTP 524）。请求内容过长或模型响应过慢，请稍后重试。"
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

    def text(
        self,
        system: str,
        user: str,
        name: str,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        selected_model = model or settings.text_model
        selected_max_tokens = max_tokens or settings.text_max_tokens
        extra_body = None
        if "dashscope.aliyuncs.com" in settings.text_base_url and selected_model.lower().startswith("qwen"):
            extra_body = {"enable_thinking": settings.text_enable_thinking}
        response = call_with_provider_retry(
            lambda: self.client.chat.completions.create(
                model=selected_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
                max_tokens=selected_max_tokens,
                extra_body=extra_body,
            ),
            "文本 API",
        )
        content = response.choices[0].message.content or ""
        self.trace.append({"node": name, "model": selected_model, "kind": "text"})
        return content.strip()

    def json(self, system: str, user: str, name: str) -> dict[str, Any]:
        raw = self.text(system, user + "\n\n只输出合法 JSON，不要 Markdown 代码围栏。", name)
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.S)
        raw = match.group(1) if match else raw
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{name} 未返回可解析 JSON：{raw[:300]}") from exc


class VisionApiClient:
    """Extracts factual information from uploaded images through the text model or an optional vision override."""

    def __init__(self) -> None:
        api_key = settings.vision_api_key or settings.text_api_key
        base_url = settings.vision_base_url or settings.text_base_url
        self.model = settings.vision_model or settings.text_model
        if not api_key:
            raise RuntimeError("图片资料需要 VISION_API_KEY 或 TEXT_API_KEY。")
        self.client = _openai_client(api_key, base_url)

    def describe(self, path: Path) -> str:
        mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
        data_url = f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
        response = call_with_provider_retry(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是企业资料整理助手。准确提取图片中的可读文字、表格、图表数据、产品信息与关键视觉事实。不要猜测看不清或图片中没有的信息。只输出可供内容写作使用的中文资料摘要。",
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"请整理这张资料图片：{path.name}"},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                ],
                temperature=0,
                max_tokens=settings.text_max_tokens,
            ),
            "视觉模型 API",
        )
        content = response.choices[0].message.content or ""
        if not content.strip():
            raise RuntimeError(f"未能从图片 {path.name} 提取有效资料")
        return content.strip()

class ImageApiClient:
    """OpenAI-compatible client for the independently configured image model API."""

    def __init__(self) -> None:
        if not settings.image_api_key:
            raise RuntimeError("缺少 IMAGE_API_KEY。请在项目根目录的 .env 中配置后重试。")
        self.client = _openai_client(settings.image_api_key, settings.image_base_url)
        self.trace: list[dict[str, Any]] = []

    def image(self, prompt: str, target: Path, *, size: str, quality: str) -> None:
        response = call_with_provider_retry(
            lambda: self.client.images.generate(
                model=settings.image_model,
                prompt=prompt,
                size=size,
                quality=quality,
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
        self.trace.append(
            {"node": "generate_images", "model": settings.image_model, "kind": "image", "file": target.name, "size": size, "quality": quality}
        )


class ContentModelHarness:
    """Coordinates independent text and image API clients and exposes one run trace."""

    def __init__(self, enable_image_generation: bool = True) -> None:
        self.text_api = TextApiClient()
        self.image_api = ImageApiClient() if enable_image_generation else None

    @property
    def trace(self) -> list[dict[str, Any]]:
        image_trace = self.image_api.trace if self.image_api else []
        return [*self.text_api.trace, *image_trace]

    def text(self, system: str, user: str, name: str) -> str:
        return self.text_api.text(system, user, name)

    def json(self, system: str, user: str, name: str) -> dict[str, Any]:
        return self.text_api.json(system, user, name)

    def image(self, prompt: str, target: Path, *, size: str, quality: str) -> None:
        if not self.image_api:
            raise RuntimeError("本次任务未启用图片生成")
        self.image_api.image(prompt, target, size=size, quality=quality)
