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


def _draw_cover_title(canvas: Image.Image, headline: str, *, light: bool = False) -> None:
    draw = ImageDraw.Draw(canvas)
    margin = 74
    title_font = _font(58, bold=True)
    title_lines = _wrapped_lines(draw, headline, title_font, CARD_SIZE[0] - margin * 2 - 44)[:2]
    title_y = 112
    fill = "#17231C" if light else "white"
    for line in title_lines:
        title_y += 76
    box_bottom = title_y + 28
    box_right = margin + max(draw.textlength(line, font=title_font) for line in title_lines) + 44
    if not light:
        overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle((margin - 20, 84, min(int(box_right), CARD_SIZE[0] - 48), box_bottom), radius=16, fill=(19, 31, 25, 188))
        canvas.alpha_composite(overlay)
    title_y = 112
    for line in title_lines:
        draw = ImageDraw.Draw(canvas)
        draw.text((margin, title_y), line, fill=fill, font=title_font)
        title_y += 76
    draw.line((margin, title_y + 10, margin + 82, title_y + 10), fill="#D39A49", width=5)


def render_card(source_path: Path | None, card: dict, card_index: int, total: int, output_path: Path) -> None:
    if source_path and source_path.exists():
        with Image.open(source_path) as source:
            canvas = _cover_crop(source)
    else:
        canvas = _demo_background(card_index)

    canvas = canvas.convert("RGBA")
    layout = card.get("layout", "实拍故事")
    is_cover = card.get("role") == "cover" or card_index == 1
    if layout == "杂志留白":
        frame = Image.new("RGBA", CARD_SIZE, "#F7F4ED")
        inset = ImageOps.fit(canvas.convert("RGB"), (932, 1130), method=Image.Resampling.LANCZOS, centering=(0.5, 0.46))
        frame.alpha_composite(inset.convert("RGBA"), (74, 150))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((74, 150, 1006, 1280), outline="#252A25", width=3)
        if is_cover:
            _draw_cover_title(frame, card["headline"], light=True)
        else:
            draw.text((74, 72), card["headline"], fill="#252A25", font=_font(34, bold=True))
        canvas = frame
    elif layout == "知识图解":
        frame = Image.new("RGBA", CARD_SIZE, "#F1F4F0")
        inset = ImageOps.fit(canvas.convert("RGB"), (932, 820), method=Image.Resampling.LANCZOS, centering=(0.5, 0.43))
        frame.alpha_composite(inset.convert("RGBA"), (74, 74))
        draw = ImageDraw.Draw(frame)
        draw.rectangle((74, 74, 1006, 894), outline="#A8B9AE", width=3)
        if is_cover:
            _draw_cover_title(frame, card["headline"], light=True)
        else:
            title_font = _font(54, bold=True)
            body_font = _font(32)
            y = 980
            for line in _wrapped_lines(draw, card["headline"], title_font, 900)[:2]:
                draw.text((74, y), line, fill="#1D3026", font=title_font)
                y += 68
            y += 20
            for line in _wrapped_lines(draw, card.get("body", ""), body_font, 900)[:3]:
                draw.text((74, y), line, fill="#526359", font=body_font)
                y += 47
        canvas = frame
    elif layout == "清单便签":
        frame = Image.new("RGBA", CARD_SIZE, "#EFE6D5")
        inset = ImageOps.fit(canvas.convert("RGB"), (900, 1000), method=Image.Resampling.LANCZOS, centering=(0.5, 0.43))
        frame.alpha_composite(inset.convert("RGBA"), (90, 90))
        draw = ImageDraw.Draw(frame)
        draw.rounded_rectangle((90, 90, 990, 1090), radius=18, outline="#4D5C4B", width=4)
        draw.ellipse((810, 1120, 930, 1240), fill="#D39A49")
        draw.text((847, 1140), str(card_index), fill="white", font=_font(54, bold=True))
        if is_cover:
            _draw_cover_title(frame, card["headline"], light=True)
        else:
            draw.text((90, 1175), card["headline"], fill="#2A3C31", font=_font(40, bold=True))
        canvas = frame
    elif is_cover:
        # The image-first and documentary variants only overlay a title on the cover.
        _draw_cover_title(canvas, card["headline"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, format="PNG", optimize=True)


def render_preview(title: str, caption: str, hashtags: list[str], cards: list[dict], job_id: str, output_path: Path) -> None:
    card_markup = "".join(
        f'<figure><img src="/assets/jobs/{job_id}/cards/{html.escape(card["filename"])}" alt="{html.escape(card["headline"])}"></figure>'
        for card in cards
    )
    tags = " ".join(html.escape(tag) for tag in hashtags)
    output_path.write_text(
        f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{margin:0;background:#f5f3ef;color:#20231f;font:15px/1.6 -apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif}}main{{max-width:1160px;margin:auto;padding:32px 20px 58px}}header{{max-width:680px;margin-bottom:28px}}.eyebrow{{color:#cd422b;font-size:12px;font-weight:700;letter-spacing:.08em}}h1{{margin:6px 0 8px;font:700 32px/1.25 Georgia,'Songti SC',serif}}p{{white-space:pre-line;color:#596057}}.tags{{color:#c43d2a;font-size:14px}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}}figure{{margin:0;background:#fff;box-shadow:0 7px 22px rgba(35,31,24,.09)}}img{{display:block;width:100%;aspect-ratio:3/4;object-fit:cover}}@media(max-width:760px){{main{{padding:22px 14px 42px}}.grid{{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}h1{{font-size:26px}}}}</style></head>
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
