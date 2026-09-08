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


def generate_reddit_title_card(
    subreddit: str,
    author: str,
    title: str,
    score: int,
    num_comments: int,
    output_path: str,
    card_width: int = 960,
    bg_color: Tuple[int, int, int, int] = (26, 26, 27, 240),  # Reddit Dark
    border_color: Tuple[int, int, int, int] = (52, 53, 54, 255),
    corner_radius: int = 24,
) -> str:
    """Generate a Reddit dark-mode styled title card image (PNG with transparency).
    
    Args:
        subreddit: e.g. 'r/AmItheAsshole'
        author: e.g. 'Throwaway123'
        title: Post title
        score: Upvote count
        num_comments: Comment count
        output_path: Path to save PNG
        
    Returns:
        Absolute path to generated PNG.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Fonts
    sub_font = get_default_font(30, bold=True)
    meta_font = get_default_font(24, bold=False)
    title_font = get_default_font(38, bold=True)
    badge_font = get_default_font(24, bold=True)

    # Temporary canvas to measure text
    temp_img = Image.new("RGBA", (card_width, 1000), (0, 0, 0, 0))
    temp_draw = ImageDraw.Draw(temp_img)

    content_width = card_width - 80  # 40px padding on each side
    wrapped_title = wrap_text(title, title_font, content_width, temp_draw)
    
    # Cap title lines to 5 lines max to avoid giant cards
    if len(wrapped_title) > 5:
        wrapped_title = wrapped_title[:5]
        wrapped_title[-1] += "..."

    line_height = 48
    title_height = len(wrapped_title) * line_height

    # Total card height: top_padding (40) + header (60) + spacing (20) + title_height + spacing (30) + footer (40) + bottom_padding (35)
    card_height = 40 + 60 + 20 + title_height + 30 + 40 + 35

    # Create final card image
    card = Image.new("RGBA", (card_width, card_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    # Draw rounded rectangle background with subtle border
    draw.rounded_rectangle(
        [(0, 0), (card_width - 1, card_height - 1)],
        radius=corner_radius,
        fill=bg_color,
        outline=border_color,
        width=2,
    )

    # --- Header: Reddit Icon + Subreddit + Author ---
    icon_x = 40
    icon_y = 35
    icon_size = 50

    # Draw Reddit Orange circular badge
    draw.ellipse(
        [(icon_x, icon_y), (icon_x + icon_size, icon_y + icon_size)],
        fill=(255, 69, 0, 255),
    )
    # White 'r/' letter inside icon
    r_font = get_default_font(28, bold=True)
    draw.text((icon_x + 13, icon_y + 8), "r/", font=r_font, fill=(255, 255, 255, 255))

    # Subreddit name & Meta
    header_text_x = icon_x + icon_size + 18
    draw.text(
        (header_text_x, icon_y + 2),
        subreddit if subreddit.startswith("r/") else f"r/{subreddit}",
        font=sub_font,
        fill=(215, 218, 220, 255),
    )

    meta_text = f"Posted by u/{author} • 14h ago"
    draw.text(
        (header_text_x, icon_y + 36),
        meta_text,
        font=meta_font,
        fill=(129, 131, 132, 255),
    )

    # --- Post Title ---
    title_y = icon_y + icon_size + 25
    for line in wrapped_title:
        draw.text(
            (40, title_y),
            line,
            font=title_font,
            fill=(255, 255, 255, 255),
        )
        title_y += line_height

    # --- Footer: Upvotes & Comments Badges ---
    footer_y = title_y + 15

    # Upvotes Pill
    score_str = f"▲  {format_score(score)}"
    draw.rounded_rectangle(
        [(40, footer_y), (180, footer_y + 42)],
        radius=21,
        fill=(40, 42, 44, 255),
    )
    draw.text((56, footer_y + 8), score_str, font=badge_font, fill=(215, 218, 220, 255))

    # Comments Pill
    comments_str = f"💬  {format_score(num_comments)}"
    draw.rounded_rectangle(
        [(195, footer_y), (335, footer_y + 42)],
        radius=21,
        fill=(40, 42, 44, 255),
    )
    draw.text((211, footer_y + 8), comments_str, font=badge_font, fill=(215, 218, 220, 255))

    card.save(output_path, "PNG")
    return os.path.abspath(output_path)
