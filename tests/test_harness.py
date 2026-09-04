import pytest

from app.config import settings
from app.harness import ContentModelHarness, ImageApiClient, TextApiClient, VisionApiClient, _openai_client, _provider_message, _retry_after_seconds
from app.gzh_adapter import _run_skill_script


def test_text_api_requires_its_own_key(monkeypatch):
    monkeypatch.setattr(settings, "text_api_key", "")
    with pytest.raises(RuntimeError, match="TEXT_API_KEY"):
        TextApiClient()


def test_image_api_requires_its_own_key(monkeypatch):
    monkeypatch.setattr(settings, "image_api_key", "")
    with pytest.raises(RuntimeError, match="IMAGE_API_KEY"):
        ImageApiClient()


def test_zero_image_tasks_do_not_require_an_image_key(monkeypatch):
    monkeypatch.setattr(settings, "text_api_key", "test-text-key")
    monkeypatch.setattr(settings, "image_api_key", "")
    harness = ContentModelHarness(enable_image_generation=False)
    assert harness.image_api is None


def test_image_materials_reuse_the_text_model_by_default(monkeypatch):
    monkeypatch.setattr(settings, "vision_model", "")
    monkeypatch.setattr(settings, "text_api_key", "test-text-key")
    monkeypatch.setattr(settings, "text_model", "qwen3.7-plus")
    client = VisionApiClient()
    assert client.model == "qwen3.7-plus"


def test_provider_retry_after_uses_cloudflare_payload():
    class ProviderError(Exception):
        body = {"error_code": 502, "retry_after": 60}
        response = None

    assert _retry_after_seconds(ProviderError()) == 60


def test_provider_message_explains_cloudflare_524():
    class ProviderError(Exception):
        status_code = 524

    assert "上游处理超时" in _provider_message("文本 API", ProviderError())


def test_api_client_uses_windows_proxy_by_default(monkeypatch):
    monkeypatch.setattr(settings, "api_use_system_proxy", True)
    client = _openai_client("test", "https://example.invalid/v1")
    assert client._client._trust_env is True


def test_qwen_text_defaults_to_non_thinking_mode():
    assert settings.text_enable_thinking is False


def test_gzh_scripts_run_with_utf8(tmp_path):
    script = tmp_path / "emit.py"
    script.write_text("print('公众号 ✅')", encoding="utf-8")
    result = _run_skill_script(script)
    assert result.returncode == 0
    assert "公众号 ✅" in result.stdout


def test_dashscope_qwen_image_uses_async_messages_and_parses_choices(monkeypatch, tmp_path):
    class Response:
        def __init__(self, payload=None, content=b"", status_code=200):
            self._payload = payload or {}
            self.content = content
            self.status_code = status_code
            self.text = "ok"

        def json(self):
            return self._payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(self.text)

    calls = {}

    def fake_post(url, **kwargs):
        calls["post"] = (url, kwargs)
        return Response({"output": {"task_id": "task-1", "task_status": "PENDING"}})

    def fake_get(url, **kwargs):
        calls.setdefault("get", []).append((url, kwargs))
        if url.endswith("/task-1"):
            return Response({"output": {"task_status": "SUCCEEDED", "choices": [{"message": {"content": [{"image": "https://img.test/result.png"}]}}]}})
        return Response(content=b"png-bytes")

    monkeypatch.setattr(settings, "image_api_key", "test-key")
    monkeypatch.setattr(settings, "image_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(settings, "image_model", "qwen-image-3.0")
    monkeypatch.setattr(settings, "request_timeout_seconds", 5)
    monkeypatch.setattr("app.harness.httpx.post", fake_post)
    monkeypatch.setattr("app.harness.httpx.get", fake_get)
    monkeypatch.setattr("app.harness.time.sleep", lambda _: None)

    target = tmp_path / "generated.png"
    ImageApiClient().image("蓝色杯子", target, size="1024x1024", quality="high")

    assert target.read_bytes() == b"png-bytes"
    url, kwargs = calls["post"]
    assert url.endswith("/api/v1/services/aigc/image-generation/generation")
    assert kwargs["headers"]["X-DashScope-Async"] == "enable"
    assert kwargs["json"]["input"]["messages"][0]["content"][0]["text"] == "蓝色杯子"
