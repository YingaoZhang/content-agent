import subprocess
import sys
from pathlib import Path

from .config import settings
from .harness import TextApiClient


THEMES = {
    "石墨极简风": "theme-graphite-minimal.md",
    "摸鱼绿": "theme-moyu-green.md",
    "红白色系": "theme-red-white.md",
    "橄榄手记": "theme-olive-journal.md",
}


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
    html_path.write_text(_clean_html(text_api.text(system, user, "gzh_layout")), encoding="utf-8")
    validator = skill_dir / "scripts" / "validate_gzh_html.py"
    validation = _run_skill_script(validator, html_path)
    warnings = [line.strip() for line in validation.stdout.splitlines() if "WARNING" in line or "ERROR" in line]
    if validation.returncode != 0:
        repair = text_api.text(system, f"以下 HTML 未通过校验，请只修复并输出完整 HTML。\n\n校验结果：\n{_diagnostics(validation)}\n\nHTML：\n{html_path.read_text(encoding='utf-8')}", "gzh_repair")
        html_path.write_text(_clean_html(repair), encoding="utf-8")
        validation = _run_skill_script(validator, html_path)
        warnings = [line.strip() for line in validation.stdout.splitlines() if "WARNING" in line or "ERROR" in line]
        if validation.returncode != 0:
            raise RuntimeError(f"gzh-design-skill 排版校验未通过：{_diagnostics(validation)}")

    preview_script = skill_dir / "scripts" / "wrap_preview.py"
    preview_path = html_path.with_name("wechat_preview.html")
    preview = _run_skill_script(preview_script, html_path, preview_path)
    if preview.returncode != 0:
        raise RuntimeError(f"gzh-design-skill 预览生成失败：{_diagnostics(preview)}")
    return html_path, preview_path, warnings
