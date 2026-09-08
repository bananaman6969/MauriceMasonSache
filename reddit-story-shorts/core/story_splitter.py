"""Story Splitter: Splits long Reddit stories into sequential parts (e.g., Part 1, Part 2)."""

import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


def split_text_into_sentences(text: str) -> List[str]:
    """Split text into sentences preserving sentence-ending punctuation."""
    # Match sentences ending with ., !, ? followed by space or newline
    sentence_endings = re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_endings.split(text.strip())
    return [s.strip() for s in sentences if s.strip()]


def split_story_into_parts(
    title: str,
    body: str,
    max_duration_seconds: int = 60,
    words_per_minute: int = 150,
    add_cta: bool = True,
) -> List[Dict[str, Any]]:
    """Split a story into multiple parts if it exceeds max_duration_seconds.
    
    Args:
        title: Post title.
        body: Cleaned story body text.
        max_duration_seconds: Target maximum duration per part (default 60s).
        words_per_minute: Speaking rate (default 150 wpm).
        add_cta: Whether to append 'Follow for part 2' hooks between parts.
        
    Returns:
        List of parts with script, part number, word count, and estimated duration.
    """
    max_words_per_part = int((max_duration_seconds / 60.0) * words_per_minute)
    
    # If the whole story fits within the target duration, return a single part
    total_words = len((title + " " + body).split())
    if total_words <= max_words_per_part:
        script = f"{title}. {body}".strip()
        words = len(script.split())
        return [{
            "part": 1,
            "total_parts": 1,
            "part_title": title,
            "script": script,
            "word_count": words,
            "est_duration_seconds": round((words / words_per_minute) * 60, 1),
        }]

    sentences = split_text_into_sentences(body)
    parts_data: List[Dict[str, Any]] = []

    # First part includes the title
    current_sentences: List[str] = []
    current_word_count = len(title.split())

    for sentence in sentences:
        s_words = len(sentence.split())
        if current_word_count + s_words > max_words_per_part and current_sentences:
            # Complete current part
            part_body = " ".join(current_sentences)
            parts_data.append({"body": part_body})
            current_sentences = [sentence]
            current_word_count = s_words
        else:
            current_sentences.append(sentence)
            current_word_count += s_words

    if current_sentences:
        parts_data.append({"body": " ".join(current_sentences)})

    total_parts = len(parts_data)
    final_parts: List[Dict[str, Any]] = []

    for idx, p in enumerate(parts_data, start=1):
        if idx == 1:
            part_title = f"{title} (Part 1)"
            cta = " Like and follow for part 2!" if (add_cta and total_parts > 1) else ""
            script = f"{title}. {p['body']}{cta}"
        else:
            part_title = f"{title} (Part {idx})"
            cta = f" Like and follow for part {idx + 1}!" if (add_cta and idx < total_parts) else ""
            script = f"Part {idx}. {p['body']}{cta}"

        words = len(script.split())
        final_parts.append({
            "part": idx,
            "total_parts": total_parts,
            "part_title": part_title,
            "script": script,
            "word_count": words,
            "est_duration_seconds": round((words / words_per_minute) * 60, 1),
        })

    return final_parts
