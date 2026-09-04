import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps


CARD_SIZE = (1080, 1440)
FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    preferred = FONT_CANDIDATES[0 if bold else 1]
    for candidate in (preferred, *FONT_CANDIDATES):
        try:
            return ImageFont.truetype(candidate, size=size, index=0)
        except OSError:
            continue
    return ImageFont.load_default()


def _cover_crop(image: Image.Image) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), CARD_SIZE, method=Image.Resampling.LANCZOS, centering=(0.5, 0.43))


def _demo_background(card_index: int) -> Image.Image:
    """Create a polished local preview when no model image is requested."""
    palettes = (
        ("#E5EEE8", "#88A79A", "#E8B26F", "#23463B"),
        ("#E6EFEA", "#B6CC82", "#D9654F", "#29463A"),
        ("#F0EBDD", "#D7AB68", "#7FA89B", "#3A4D42"),
        ("#E5EEEC", "#77A8A1", "#E0C878", "#21483E"),
        ("#EFF0DF", "#9FB56B", "#D98262", "#2C4B3C"),
        ("#E8EEE5", "#9AB8A6", "#DFA865", "#28483D"),
    )
    base, accent, warm, ink = palettes[(card_index - 1) % len(palettes)]
    canvas = Image.new("RGB", CARD_SIZE, base)
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((650, -210, 1240, 380), fill=accent)
    draw.ellipse((-180, 420, 280, 880), fill=warm)
    draw.rounded_rectangle((145, 270, 825, 680), radius=38, fill="#FAFAF5", outline=ink, width=5)
    draw.rounded_rectangle((280, 410, 965, 750), radius=38, fill="#F7F2E7", outline=ink, width=5)
    for offset, width in ((0, 360), (82, 495), (164, 265)):
        draw.rounded_rectangle((215 + offset // 3, 345 + offset, 215 + offset // 3 + width, 367 + offset), radius=11, fill=accent)
    draw.line((770, 300, 920, 180), fill=ink, width=12)
    draw.line((920, 180, 980, 275), fill=ink, width=12)
    draw.line((920, 180, 815, 170), fill=ink, width=12)
    draw.ellipse((718, 640, 830, 752), fill=warm, outline=ink, width=5)
    draw.ellipse((845, 550, 930, 635), fill=accent, outline=ink, width=5)
    return canvas


def _wrapped_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        current = ""
        for character in paragraph:
            candidate = current + character
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = character
            else:
                current = candidate
        if current:
            lines.append(current)
    return lines


def render_card(source_path: Path | None, card: dict, card_index: int, total: int, brand_name: str, output_path: Path) -> None:
    if source_path and source_path.exists():
        with Image.open(source_path) as source:
            canvas = _cover_crop(source)
    else:
        canvas = _demo_background(card_index)

    canvas = canvas.convert("RGBA")
    overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rectangle((0, 720, CARD_SIZE[0], CARD_SIZE[1]), fill=(17, 28, 23, 188))
    canvas = Image.alpha_composite(canvas, overlay)
    draw = ImageDraw.Draw(canvas)

    margin = 74
    eyebrow_font = _font(27, bold=True)
    title_font = _font(72, bold=True)
    body_font = _font(35)
    # Keep the image area clean: brand/topic text is already in the card headline.

    title_lines = _wrapped_lines(draw, card["headline"], title_font, CARD_SIZE[0] - margin * 2)
    title_lines = title_lines[:2]
    title_y = 830 if len(title_lines) == 1 else 760
    for line in title_lines:
        draw.text((margin, title_y), line, fill="white", font=title_font, stroke_width=1, stroke_fill="#182B22")
        title_y += 94

    draw.line((margin, title_y + 8, margin + 120, title_y + 8), fill="#CBE6B6", width=7)
    body_y = title_y + 48
    for line in _wrapped_lines(draw, card["body"], body_font, CARD_SIZE[0] - margin * 2)[:4]:
        draw.text((margin, body_y), line, fill="#F5F8F2", font=body_font)
        body_y += 54
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, format="PNG", optimize=True)


def render_preview(title: str, caption: str, hashtags: list[str], cards: list[dict], job_id: str, output_path: Path) -> None:
    card_markup = "".join(
        f'<figure><img src="/assets/jobs/{job_id}/cards/{html.escape(card["filename"])}" alt="{html.escape(card["headline"])}"><figcaption>{index + 1} / {len(cards)} · {html.escape(card["headline"])}</figcaption></figure>'
        for index, card in enumerate(cards)
    )
    tags = " ".join(html.escape(tag) for tag in hashtags)
    output_path.write_text(
        f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{margin:0;background:#f5f3ef;color:#20231f;font:15px/1.6 -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif}}main{{max-width:1160px;margin:auto;padding:32px 20px 58px}}header{{max-width:680px;margin-bottom:28px}}.eyebrow{{color:#cd422b;font-size:12px;font-weight:700;letter-spacing:.08em}}h1{{margin:6px 0 8px;font:700 32px/1.25 Georgia,'Songti SC',serif}}p{{white-space:pre-line;color:#596057}}.tags{{color:#c43d2a;font-size:14px}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}}figure{{margin:0;background:#fff;box-shadow:0 7px 22px rgba(35,31,24,.09)}}img{{display:block;width:100%;aspect-ratio:3/4;object-fit:cover}}figcaption{{padding:10px 12px;color:#657068;font-size:12px}}@media(max-width:760px){{main{{padding:22px 14px 42px}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}h1{{font-size:26px}}}}</style></head>
<body><main><header><div class="eyebrow">XIAOHONGSHU · 图文笔记</div><h1>{html.escape(title)}</h1><p>{html.escape(caption)}</p><div class="tags">{tags}</div></header><section class="grid">{card_markup}</section></main></body></html>""",
        encoding="utf-8",
    )


def write_note_files(job_dir: Path, title: str, caption: str, hashtags: list[str], cards: list[dict], job_id: str) -> Path:
    note = f"# {title}\n\n{caption}\n\n{' '.join(hashtags)}\n"
    (job_dir / "article.md").write_text(note, encoding="utf-8")
    (job_dir / "article_with_images.md").write_text(note, encoding="utf-8")
    (job_dir / "caption.txt").write_text(f"{title}\n\n{caption}\n\n{' '.join(hashtags)}\n", encoding="utf-8")
    (job_dir / "card_plan.json").write_text(json.dumps({"title": title, "caption": caption, "hashtags": hashtags, "cards": cards}, ensure_ascii=False, indent=2), encoding="utf-8")
    preview_path = job_dir / "xiaohongshu_preview.html"
    render_preview(title, caption, hashtags, cards, job_id, preview_path)
    return preview_path
