from pathlib import Path

from app.gzh_adapter import _ensure_markdown_images, render_wechat_html
from app.harness import ProviderUnavailableError


class TimeoutTextApi:
    def text(self, *args, **kwargs):
        raise ProviderUnavailableError("文本 API上游处理超时（HTTP 524）。")


def test_layout_timeout_uses_local_wechat_fallback(tmp_path: Path):
    markdown = """# 测试标题

一段中文正文，包含**重点**。

## 第一部分

![配图](/assets/jobs/demo/images/cover.png)

- 第一项
- 第二项
"""
    html_path, preview_path, warnings = render_wechat_html(TimeoutTextApi(), markdown, "石墨极简风", tmp_path)

    html = html_path.read_text(encoding="utf-8")
    assert html_path.exists()
    assert preview_path.exists()
    assert '<span leaf="">测试标题</span>' in html
    assert 'src="/assets/jobs/demo/images/cover.png"' in html
    assert any("基础本地排版" in warning for warning in warnings)


def test_layout_image_guard_restores_images_omitted_by_the_layout_model():
    markdown = """# 标题

![封面](/assets/jobs/demo/images/cover.png)

## 第一节

![章节插图](/assets/jobs/demo/images/body.png)
"""
    html, warnings = _ensure_markdown_images(markdown, '<section><p><span leaf="">正文</span></p></section>')

    assert html.count("<img") == 2
    assert 'src="/assets/jobs/demo/images/cover.png"' in html
    assert 'src="/assets/jobs/demo/images/body.png"' in html
    assert warnings == ["排版器遗漏了 2 张配图，系统已自动补齐。"]


def test_layout_image_guard_leaves_retained_images_unchanged():
    markdown = "![封面](/assets/jobs/demo/images/cover.png)"
    source_html = '<section><img src="/assets/jobs/demo/images/cover.png"></section>'

    html, warnings = _ensure_markdown_images(markdown, source_html)

    assert html == source_html
    assert warnings == []
