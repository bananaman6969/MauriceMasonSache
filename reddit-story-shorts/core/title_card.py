"""Title Card Generator: Renders an authentic Reddit post header card using Pillow."""

import os
import math
import logging
from typing import Optional, Tuple
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def get_default_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Attempt to load system or local font, fallback to default."""
    font_names = []
    if bold:
        font_names = ["arialbd.ttf", "segoeuib.ttf", "seguisb.ttf", "calibrib.ttf"]
    else:
        font_names = ["arial.ttf", "segoeui.ttf", "calibri.ttf"]

    for name in font_names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue

    try:
        return ImageFont.load_default()
    except Exception:
        return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    """Wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current_line = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        line_width = bbox[2] - bbox[0]
        if line_width <= max_width:
            current_line.append(word)
        else:
            if current_line:
                lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))

    return lines


def format_score(score: int) -> str:
    """Format score to human readable string e.g. 14.5k."""
    if score >= 1_000_000:
        return f"{score / 1_000_000:.1f}M"
    if score >= 1_000:
        return f"{score / 1_000:.1f}k"
    return str(score)


def draw_snoo_avatar(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 54):
    """Draw an authentic Reddit Snoo alien avatar."""
    draw.ellipse([(x, y), (x + size, y + size)], fill=(255, 69, 0, 255))
    cx = x + size // 2
    cy = y + size // 2 + 2
    # Ears
    draw.ellipse([(cx - 20, cy - 8), (cx - 12, cy)], fill=(255, 255, 255, 255))
    draw.ellipse([(cx + 12, cy - 8), (cx + 20, cy)], fill=(255, 255, 255, 255))
    # Head oval
    draw.ellipse([(cx - 15, cy - 9), (cx + 15, cy + 9)], fill=(255, 255, 255, 255))
    # Antenna
    draw.line([(cx, cy - 9), (cx + 6, cy - 18)], fill=(255, 255, 255, 255), width=2)
    draw.ellipse([(cx + 4, cy - 22), (cx + 10, cy - 16)], fill=(255, 255, 255, 255))
    # Eyes (Orange dots)
    draw.ellipse([(cx - 8, cy - 2), (cx - 4, cy + 2)], fill=(255, 69, 0, 255))
    draw.ellipse([(cx + 4, cy - 2), (cx + 8, cy + 2)], fill=(255, 69, 0, 255))
    # Smile
    draw.arc([(cx - 6, cy + 1), (cx + 6, cy + 6)], start=10, end=170, fill=(26, 26, 27, 255), width=2)


def draw_comment_icon(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 18):
    color = (215, 218, 220, 255)
    w = size
    h = int(size * 0.75)
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=3, outline=color, width=2)
    draw.polygon([(x + 3, y + h), (x + 3, y + h + 5), (x + 9, y + h)], fill=color)


def draw_share_icon(draw: ImageDraw.ImageDraw, x: int, y: int, size: int = 18):
    color = (215, 218, 220, 255)
    draw.arc([(x, y + 4), (x + size - 2, y + size + 6)], start=180, end=270, fill=color, width=2)
    draw.polygon([(x + size, y + 2), (x + size - 8, y - 2), (x + size - 8, y + 6)], fill=color)


def draw_upvote_arrow(draw: ImageDraw.ImageDraw, x: int, y: int, w: int = 14, h: int = 12):
    color = (160, 163, 166, 255)
    draw.polygon([(x + w // 2, y), (x, y + h), (x + w, y + h)], fill=color)


def draw_downvote_arrow(draw: ImageDraw.ImageDraw, x: int, y: int, w: int = 14, h: int = 12):
    color = (160, 163, 166, 255)
    draw.polygon([(x, y), (x + w, y), (x + w // 2, y + h)], fill=color)


def generate_reddit_title_card(
    subreddit: str,
    author: str,
    title: str,
    score: int,
    num_comments: int,
    output_path: str,
    card_width: int = 960,
    bg_color: Tuple[int, int, int, int] = (26, 26, 27, 245),  # Reddit Dark
    border_color: Tuple[int, int, int, int] = (52, 53, 54, 255),
    corner_radius: int = 22,
) -> str:
    """Generate an authentic Reddit screenshot-styled title card image with drop shadow."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    shadow_margin = 16
    inner_card_w = card_width - (shadow_margin * 2)
    pad = 32

    # Fonts
    sub_font = get_default_font(28, bold=True)
    meta_font = get_default_font(22, bold=False)
    title_font = get_default_font(36, bold=True)
    badge_font = get_default_font(22, bold=True)
    join_font = get_default_font(22, bold=True)

    # Temporary canvas to measure text
    temp_img = Image.new("RGBA", (inner_card_w, 1200), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)

    content_width = inner_card_w - (pad * 2)
    wrapped_title = wrap_text(title, title_font, content_width, temp_draw)
    if len(wrapped_title) > 5:
        wrapped_title = wrapped_title[:5]
        wrapped_title[-1] += "..."

    line_height = 46
    title_height = len(wrapped_title) * line_height

    inner_card_h = pad + 54 + 18 + title_height + 20 + 44 + pad
    total_w = card_width
    total_h = inner_card_h + (shadow_margin * 2)

    # Canvas
    card = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))

    # 1. Soft Realistic Drop Shadow
    from PIL import ImageFilter
    shadow_mask = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow_mask)
    sdraw.rounded_rectangle(
        [(shadow_margin, shadow_margin + 6), (shadow_margin + inner_card_w, shadow_margin + inner_card_h + 6)],
        radius=corner_radius,
        fill=(0, 0, 0, 150),
    )
    shadow_blur = shadow_mask.filter(ImageFilter.GaussianBlur(12))
    card.paste(shadow_blur, (0, 0), shadow_blur)

    # 2. Main Card Body
    card_layer = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card_layer)

    bx1 = shadow_margin
    by1 = shadow_margin
    bx2 = shadow_margin + inner_card_w
    by2 = shadow_margin + inner_card_h

    draw.rounded_rectangle(
        [(bx1, by1), (bx2, by2)],
        radius=corner_radius,
        fill=bg_color,
        outline=border_color,
        width=2,
    )

    # --- Header: Snoo Avatar + Subreddit + Time + Author + Join Button ---
    avatar_x = bx1 + pad
    avatar_y = by1 + pad
    draw_snoo_avatar(draw, avatar_x, avatar_y, 54)

    header_text_x = avatar_x + 54 + 14
    clean_sub = subreddit if subreddit.startswith("r/") else f"r/{subreddit}"
    draw.text((header_text_x, avatar_y + 2), clean_sub, font=sub_font, fill=(215, 218, 220, 255))

    sub_bbox = draw.textbbox((header_text_x, avatar_y + 2), clean_sub, font=sub_font)
    dot_x = sub_bbox[2] + 10
    draw.text((dot_x, avatar_y + 5), "•  5 hr. ago", font=meta_font, fill=(129, 131, 132, 255))
    clean_author = author if author.startswith("u/") else f"u/{author}"
    draw.text((header_text_x, avatar_y + 32), clean_author, font=meta_font, fill=(129, 131, 132, 255))

    # Right side: Blue Join Button + Meatball Menu
    join_w = 80
    join_h = 34
    join_x = bx2 - pad - join_w - 36
    join_y = avatar_y + 8
    draw.rounded_rectangle(
        [(join_x, join_y), (join_x + join_w, join_y + join_h)],
        radius=17,
        fill=(0, 121, 211, 255),  # Reddit Blue
    )
    draw.text((join_x + 18, join_y + 6), "Join", font=join_font, fill=(255, 255, 255, 255))
    draw.text((bx2 - pad - 24, avatar_y + 8), "•••", font=get_default_font(24, bold=True), fill=(129, 131, 132, 255))

    # --- Post Title ---
    title_y = avatar_y + 54 + 20
    for line in wrapped_title:
        draw.text((avatar_x, title_y), line, font=title_font, fill=(242, 244, 245, 255))
        title_y += line_height

    # --- Footer Action Bar: Upvotes, Comments, Share ---
    foot_y = title_y + 16

    # 1. Vote Pill: [ ▲ 38.4k ▼ ]
    vote_w = 175
    draw.rounded_rectangle(
        [(avatar_x, foot_y), (avatar_x + vote_w, foot_y + 44)],
        radius=22,
        fill=(39, 41, 43, 255),
        outline=(52, 53, 54, 200),
        width=1,
    )
    draw_upvote_arrow(draw, avatar_x + 18, foot_y + 16, w=14, h=12)
    draw.text((avatar_x + 44, foot_y + 9), format_score(score), font=badge_font, fill=(215, 218, 220, 255))
    draw_downvote_arrow(draw, avatar_x + 140, foot_y + 16, w=14, h=12)

    # 2. Comments Pill: [ 💬 4.1k ]
    comm_x = avatar_x + vote_w + 14
    comm_w = 145
    draw.rounded_rectangle(
        [(comm_x, foot_y), (comm_x + comm_w, foot_y + 44)],
        radius=22,
        fill=(39, 41, 43, 255),
        outline=(52, 53, 54, 200),
        width=1,
    )
    draw_comment_icon(draw, comm_x + 20, foot_y + 14, size=18)
    draw.text((comm_x + 52, foot_y + 9), format_score(num_comments), font=badge_font, fill=(215, 218, 220, 255))

    # 3. Share Pill: [ ↗ Share ]
    share_x = comm_x + comm_w + 14
    share_w = 140
    draw.rounded_rectangle(
        [(share_x, foot_y), (share_x + share_w, foot_y + 44)],
        radius=22,
        fill=(39, 41, 43, 255),
        outline=(52, 53, 54, 200),
        width=1,
    )
    draw_share_icon(draw, share_x + 20, foot_y + 13, size=18)
    draw.text((share_x + 50, foot_y + 9), "Share", font=badge_font, fill=(215, 218, 220, 255))

    card.paste(card_layer, (0, 0), card_layer)
    card.save(output_path, "PNG")
    return os.path.abspath(output_path)
