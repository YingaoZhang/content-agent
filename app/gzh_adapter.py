import html
import re
import subprocess
import sys
from pathlib import Path

from .config import settings
from .harness import ProviderUnavailableError, TextApiClient


THEMES = {
    "石墨极简风": "theme-graphite-minimal.md",
    "摸鱼绿": "theme-moyu-green.md",
    "红白色系": "theme-red-white.md",
    "留白禅意风": "theme-zen-whitespace.md",
    "摸鱼票据风": "theme-moyu-ticket.md",
    "橄榄手记": "theme-olive-journal.md",
}

MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^]]*)\]\(([^\s)]+)(?:\s+[^)]*)?\)")


def _clean_html(value: str) -> str:
    return value.removeprefix("```html").removeprefix("```").removesuffix("```").strip()


def _run_skill_script(script: Path, *args: Path) -> subprocess.CompletedProcess[str]:
    """Force UTF-8 so gzh-design-skill's Chinese and emoji diagnostics work on Windows."""
    return subprocess.run(
        [sys.executable, "-X", "utf8", str(script), *(str(arg) for arg in args)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _diagnostics(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()


def _normalize_punctuation(value: str) -> str:
    return re.sub(r"(?<=[\u4e00-\u9fff])([,;!?])", lambda match: {",": "，", ";": "；", "!": "！", "?": "？"}[match.group(1)], value)


def _inline_markdown(value: str) -> str:
    escaped = html.escape(_normalize_punctuation(value), quote=False)
    escaped = re.sub(
        r"!\[([^]]*)\]\(([^\s)]+)(?:\s+[^)]*)?\)",
        lambda match: (
            f'<img src="{html.escape(match.group(2), quote=True)}" '
            f'alt="{html.escape(match.group(1), quote=True)}" '
            'style="max-width:100%;height:auto;display:block;margin:18px auto;"/>'
        ),
        escaped,
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return f'<span leaf="">{escaped}</span>'


def _image_component(source: str, alt: str) -> str:
    caption = (
        '<p style="font-size:12px;color:#9CA3AF;text-align:center;margin:0 0 24px;">'
        f'<span leaf="">— {html.escape(alt, quote=False)}</span></p>'
        if alt
        else ""
    )
    margin = "8px" if caption else "10px"
    return (
        f'<section style="background:#FFF;border-radius:12px;padding:6px;border:1px solid #E5E7EB;box-shadow:0 4px 12px -2px rgba(0,0,0,0.08);margin-bottom:{margin};">'
        '<section style="margin:0;border-radius:8px;overflow:hidden;">'
        f'<span leaf=""><img src="{html.escape(source, quote=True)}" alt="{html.escape(alt, quote=True)}" style="max-width:100%;height:auto;display:block;margin:0 auto;"></span>'
        "</section></section>"
        + caption
    )


def _ensure_markdown_images(markdown: str, rendered_html: str) -> tuple[str, list[str]]:
    """Retain every generated image even if the layout model silently omits one."""
    missing = [(alt, source) for alt, source in MARKDOWN_IMAGE_PATTERN.findall(markdown) if source not in rendered_html]
    if not missing:
        return rendered_html, []
    additions = "\n".join(_image_component(source, alt) for alt, source in missing)
    closing_root = rendered_html.rfind("</section>")
    if closing_root < 0:
        raise RuntimeError("公众号排版结果缺少外层 section，无法补齐遗漏图片")
    repaired_html = f"{rendered_html[:closing_root]}\n{additions}\n{rendered_html[closing_root:]}"
    return repaired_html, [f"排版器遗漏了 {len(missing)} 张配图，系统已自动补齐。"]


def _render_local_html(markdown: str, output_path: Path) -> None:
    """Produce a conservative WeChat-compatible fallback when remote layout is unavailable."""
    parts: list[str] = [
        '<section style="padding:12px 18px;box-sizing:border-box;line-height:1.85;color:#242424;font-size:16px;letter-spacing:0;">'
    ]
    paragraph: list[str] = []
    list_items: list[str] = []
    list_tag = "ul"

    def flush_paragraph() -> None:
        if paragraph:
            text = "<br/>".join(_inline_markdown(line) for line in paragraph)
            parts.append(f'<p style="margin:0 0 18px;text-align:justify;">{text}</p>')
            paragraph.clear()

    def flush_list() -> None:
        if list_items:
            parts.append(
                f'<{list_tag} style="margin:0 0 18px;padding-left:1.4em;">'
                + "".join(f'<li style="margin:0 0 8px;">{_inline_markdown(item)}</li>' for item in list_items)
                + f'</{list_tag}>'
            )
            list_items.clear()

    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            flush_list()
            level, text = len(heading.group(1)), heading.group(2)
            if level == 1:
                style = "margin:8px 0 24px;font-size:25px;line-height:1.45;font-weight:700;color:#1f1f1f;"
            elif level == 2:
                style = "margin:30px 0 14px;padding-left:10px;border-left:4px solid #3f7d65;font-size:20px;line-height:1.5;font-weight:700;color:#263d34;"
            else:
                style = "margin:22px 0 10px;font-size:17px;line-height:1.6;font-weight:700;color:#345d4c;"
            parts.append(f'<section style="{style}">{_inline_markdown(text)}</section>')
            continue
        unordered = re.match(r"^[-*+]\s+(.+)$", line)
        ordered = re.match(r"^\d+[.)]\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            next_tag = "ol" if ordered else "ul"
            if list_items and next_tag != list_tag:
                flush_list()
            list_tag = next_tag
            list_items.append((ordered or unordered).group(1))
            continue
        quote = re.match(r"^>\s?(.+)$", line)
        if quote:
            flush_paragraph()
            flush_list()
            parts.append(
                '<section style="margin:0 0 18px;padding:14px 16px;background:#f3f7f4;border-left:4px solid #75a58d;">'
                f'<p style="margin:0;line-height:1.8;color:#395b4b;">{_inline_markdown(quote.group(1))}</p></section>'
            )
            continue
        if re.fullmatch(r"!\[([^]]*)\]\(([^\s)]+)(?:\s+[^)]*)?\)", line):
            flush_paragraph()
            flush_list()
            parts.append(f'<section style="margin:0 0 20px;">{_inline_markdown(line)}</section>')
            continue
        paragraph.append(line)

    flush_paragraph()
    flush_list()
    parts.append("</section>")
    output_path.write_text("\n".join(parts), encoding="utf-8")


def render_wechat_html(text_api: TextApiClient, markdown: str, theme: str, output_dir: Path) -> tuple[Path, Path, list[str]]:
    skill_dir = settings.gzh_skill_dir
    theme_file = skill_dir / "references" / THEMES.get(theme, THEMES["石墨极简风"])
    common_file = skill_dir / "references" / "common-components.md"
    if not theme_file.exists() or not common_file.exists():
        raise RuntimeError("未找到 gzh-design-skill 组件库。请确认 vendor/gzh-design-skill 完整存在。")

    system = """你是微信公众号排版执行器。必须严格遵守用户提供的 gzh-design-skill 主题组件库。
只输出可粘贴到微信公众号编辑器的 HTML 正文片段：以 <section> 开始，不要 <!DOCTYPE>、html、head、body、style、script、div、class 或 id。
所有 CSS 必须内联；所有中文文字节点均放在 <span leaf=\"\"> 内；正文标点使用中文全角。
必须保留 Markdown 的实质内容，不得编造事实。图片必须保留并使用 Markdown 中给出的 src。"""
    user = f"""主题组件库：\n{theme_file.read_text(encoding='utf-8')}\n\n通用组件库：\n{common_file.read_text(encoding='utf-8')}\n\n待排版 Markdown：\n{markdown}"""
    html_path = output_dir / "wechat.html"
    validator = skill_dir / "scripts" / "validate_gzh_html.py"
    warnings: list[str] = []
    try:
        html_path.write_text(
            _clean_html(
                text_api.text(
                    system,
                    user,
                    "gzh_layout",
                    model=settings.layout_model or settings.text_model,
                    max_tokens=settings.layout_max_tokens,
                )
            ),
            encoding="utf-8",
        )
        rendered_html, image_warnings = _ensure_markdown_images(markdown, html_path.read_text(encoding="utf-8"))
        html_path.write_text(rendered_html, encoding="utf-8")
        warnings.extend(image_warnings)
        validation = _run_skill_script(validator, html_path)
        if validation.returncode != 0:
            repair = text_api.text(
                system,
                f"以下 HTML 未通过校验，请只修复并输出完整 HTML。\n\n校验结果：\n{_diagnostics(validation)}\n\nHTML：\n{html_path.read_text(encoding='utf-8')}",
                "gzh_repair",
                model=settings.layout_model or settings.text_model,
                max_tokens=settings.layout_max_tokens,
            )
            html_path.write_text(_clean_html(repair), encoding="utf-8")
            rendered_html, image_warnings = _ensure_markdown_images(markdown, html_path.read_text(encoding="utf-8"))
            html_path.write_text(rendered_html, encoding="utf-8")
            warnings.extend(image_warnings)
            validation = _run_skill_script(validator, html_path)
            if validation.returncode != 0:
                raise RuntimeError(f"gzh-design-skill 排版校验未通过：{_diagnostics(validation)}")
        warnings.extend(line.strip() for line in validation.stdout.splitlines() if "WARNING" in line)
    except ProviderUnavailableError:
        _render_local_html(markdown, html_path)
        validation = _run_skill_script(validator, html_path)
        if validation.returncode != 0:
            raise RuntimeError(f"本地基础排版校验未通过：{_diagnostics(validation)}")
        warnings.append("AI 公众号排版请求超时，本次使用基础本地排版恢复预览。")

    preview_script = skill_dir / "scripts" / "wrap_preview.py"
    preview_path = html_path.with_name("wechat_preview.html")
    preview = _run_skill_script(preview_script, html_path, preview_path)
    if preview.returncode != 0:
        raise RuntimeError(f"gzh-design-skill 预览生成失败：{_diagnostics(preview)}")
    return html_path, preview_path, warnings
