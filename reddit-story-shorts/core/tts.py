"""TTS Engine: Generates neural speech and exact word-level timings using edge-tts."""

import os
import asyncio
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
import edge_tts

logger = logging.getLogger(__name__)

CURATED_VOICES = [
    {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher (Authoritative / Narrative)",
        "gender": "Male",
        "locale": "en-US",
    },
    {
        "id": "en-US-GuyNeural",
        "name": "Guy (Casual / Energetic)",
        "gender": "Male",
        "locale": "en-US",
    },
    {
        "id": "en-US-EricNeural",
        "name": "Eric (Conversational / Warm)",
        "gender": "Male",
        "locale": "en-US",
    },
    {
        "id": "en-US-JennyNeural",
        "name": "Jenny (Clear / Expressive)",
        "gender": "Female",
        "locale": "en-US",
    },
    {
        "id": "en-US-AvaNeural",
        "name": "Ava (Young / Dynamic)",
        "gender": "Female",
        "locale": "en-US",
    },
    {
        "id": "en-GB-RyanNeural",
        "name": "Ryan (British Storyteller)",
        "gender": "Male",
        "locale": "en-GB",
    },
    {
        "id": "en-GB-SoniaNeural",
        "name": "Sonia (British Narrative)",
        "gender": "Female",
        "locale": "en-GB",
    },
]


@dataclass(frozen=True)
class WordTiming:
    word: str
    start: float  # In seconds
    end: float  # In seconds

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TTSResult:
    audio_path: str
    duration: float
    words: List[WordTiming]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audio_path": self.audio_path,
            "duration": self.duration,
            "words": [w.to_dict() for w in self.words],
        }


async def generate_speech_with_timings(
    text: str,
    output_path: str,
    voice: str = "en-US-ChristopherNeural",
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
) -> TTSResult:
    """Generate audio MP3 and word-level timestamps using edge-tts.
    
    Args:
        text: Script text to narrate.
        output_path: Target .mp3 file path.
        voice: edge-tts voice ID.
        rate: Speed modifier, e.g. "+5%" or "-10%".
        volume: Volume modifier, e.g. "+0%".
        pitch: Pitch modifier, e.g. "+0Hz".
        
    Returns:
        TTSResult containing output audio path, total duration, and word timings.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
        boundary="WordBoundary",
    )

    words: List[WordTiming] = []
    audio_bytes = bytearray()

    async for chunk in communicate.stream():
        chunk_type = chunk.get("type")
        if chunk_type == "audio":
            audio_bytes.extend(chunk.get("data", b""))
        elif chunk_type == "WordBoundary":
            # Microsoft Cognitive Services returns offset & duration in 100-nanosecond units (ticks)
            # 1 tick = 100 ns = 0.0001 ms = 0.0000001 s (10,000,000 ticks = 1 second)
            offset_ticks = chunk.get("offset", 0)
            duration_ticks = chunk.get("duration", 0)
            word_text = chunk.get("text", "").strip()

            if word_text:
                start_sec = offset_ticks / 10_000_000.0
                end_sec = (offset_ticks + duration_ticks) / 10_000_000.0
                words.append(WordTiming(word=word_text, start=round(start_sec, 3), end=round(end_sec, 3)))

    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    total_duration = words[-1].end if words else 0.0

    return TTSResult(
        audio_path=output_path,
        duration=total_duration,
        words=words,
    )


async def get_available_voices(locale_prefix: Optional[str] = "en-") -> List[Dict[str, Any]]:
    """Return available Edge TTS voices filtered by locale."""
    try:
        all_voices = await edge_tts.list_voices()
        if not locale_prefix:
            return all_voices

        filtered = [
            {
                "id": v["ShortName"],
                "name": f"{v['FriendlyName']} ({v['Gender']})",
                "gender": v["Gender"],
                "locale": v["Locale"],
            }
            for v in all_voices
            if v.get("Locale", "").lower().startswith(locale_prefix.lower())
        ]
        return filtered
    except Exception as err:
        logger.error(f"Failed to fetch edge-tts voice list: {err}")
        return CURATED_VOICES
