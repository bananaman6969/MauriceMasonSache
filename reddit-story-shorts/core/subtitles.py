"""Subtitle Engine: Generates high-retention TikTok-style ASS and SRT subtitles with word highlighting."""

import os
import logging
from typing import List, Dict, Any, Optional
from core.tts import WordTiming

logger = logging.getLogger(__name__)


def format_ass_timestamp(seconds: float) -> str:
    """Format seconds into ASS timestamp format: H:MM:SS.cc"""
    ticks = round(max(0, seconds) * 100)
    total_seconds, centis = divmod(ticks, 100)
    hrs, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    return f"{hrs}:{mins:02d}:{secs:02d}.{centis:02d}"


def format_srt_timestamp(seconds: float) -> str:
    """Format seconds into SRT timestamp format: HH:MM:SS,mmm"""
    ticks = round(max(0, seconds) * 1000)
    total_seconds, millis = divmod(ticks, 1000)
    hrs, remainder = divmod(total_seconds, 3600)
    mins, secs = divmod(remainder, 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"


def group_speech_words(words, words_per_group=3, pause_seconds=0.35):
    """Keep caption groups within spoken phrases rather than across pauses."""
    if words_per_group < 1:
        raise ValueError("words_per_group must be positive")
    groups, current = [], []
    for word in words:
        if current and (len(current) >= words_per_group
                        or current[-1].word.rstrip().endswith((".", "!", "?", ";"))
                        or word.start - current[-1].end >= pause_seconds):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    return groups


def generate_karaoke_ass(
    words: List[WordTiming],
    output_path: str,
    font_name: str = "Arial Black",
    font_size: int = 70,
    words_per_group: int = 3,
    active_color: str = "&H0000E6FF&",  # Bright Yellow (BGR format in ASS)
    inactive_color: str = "&H00FFFFFF&",  # Pure White
    outline_color: str = "&H00000000&",  # Solid Black
    outline_width: int = 4,
    shadow_depth: int = 2,
    margin_v: int = 880,  # Centered vertically in 1080x1920 (Y ≈ 960-1040)
    uppercase: bool = True,
) -> str:
    """Generate TikTok-style word-by-word highlighted ASS subtitles.
    
    Each line displays a group of 2-4 words, highlighting the currently spoken word
    with a vibrant accent color.
    
    Returns:
        Absolute path to the generated .ass file.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    if not words:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("")
        return output_path

    chunks = group_speech_words(words, words_per_group)

    lines: List[str] = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{font_size},{inactive_color},&H000000FF,{outline_color},&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline_width},{shadow_depth},2,40,40,{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    for chunk in chunks:
        # Within this chunk, create a dialogue event for each active word
        for active_idx, active_word in enumerate(chunk):
            w_start = format_ass_timestamp(active_word.start)
            next_word = chunk[active_idx + 1] if active_idx + 1 < len(chunk) else None
            end = min(active_word.end, next_word.start) if next_word else active_word.end
            w_end = format_ass_timestamp(end)

            # Build line text with current word highlighted
            formatted_words = []
            for idx, w in enumerate(chunk):
                txt = w.word.upper() if uppercase else w.word
                if idx == active_idx:
                    formatted_words.append(f"{{\\c{active_color}}}{txt}{{\\c{inactive_color}}}")
                else:
                    formatted_words.append(txt)

            line_text = " ".join(formatted_words)
            if end > active_word.start and w_end != w_start:
                lines.append(f"Dialogue: 0,{w_start},{w_end},Default,,0,0,0,,{line_text}")
            # Hold the phrase during small gaps, with no falsely active word.
            if next_word and next_word.start > end:
                neutral = " ".join(w.word.upper() if uppercase else w.word for w in chunk)
                neutral_start, neutral_end = format_ass_timestamp(end), format_ass_timestamp(next_word.start)
                if neutral_start != neutral_end:
                    lines.append(f"Dialogue: 0,{neutral_start},{neutral_end},Default,,0,0,0,,{neutral}")

    content = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return os.path.abspath(output_path)


def generate_srt_subtitles(
    words: List[WordTiming],
    output_path: str,
    words_per_group: int = 3,
) -> str:
    """Generate standard .srt subtitles file as an alternate export."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if not words:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("")
        return output_path

    srt_entries: List[str] = []
    entry_num = 1

    for chunk in group_speech_words(words, words_per_group):
        start_ts = format_srt_timestamp(chunk[0].start)
        end_ts = format_srt_timestamp(chunk[-1].end)
        text = " ".join(w.word for w in chunk)

        srt_entries.append(f"{entry_num}\n{start_ts} --> {end_ts}\n{text}\n")
        entry_num += 1

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(srt_entries))

    return os.path.abspath(output_path)
