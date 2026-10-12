import asyncio
from types import SimpleNamespace
import pytest
from core.kokoro_tts import token_timings, VOICES
from core.tts import WordTiming, TTSResult
import core.tts as tts


def token(text, start, end, whitespace=" "):
    return SimpleNamespace(text=text, start_ts=start, end_ts=end, whitespace=whitespace)


def test_token_alignment_joins_contractions_and_adds_audio_offset():
    words = token_timings([token("do", .1, .2, ""), token("n't", .2, .4),
                          token("panic", .5, .8, ""), token(".", None, None)], 3, 1)
    assert words == [WordTiming("don't", 3.1, 3.4), WordTiming("panic.", 3.5, 3.8)]


def test_missing_timestamps_are_not_guessed():
    with pytest.raises(RuntimeError, match="could not time"):
        token_timings([token("unknown", None, None)], 0, 1)


def test_punctuation_pause_does_not_extend_word_highlight():
    words = token_timings([token("Hello", .1, .4, ""), token(".", .4, .8)], 0, 1)
    assert words == [WordTiming("Hello.", .1, .4)]


@pytest.mark.asyncio
async def test_local_dispatch_and_cache_preserve_model_timings(tmp_path, monkeypatch):
    import core.kokoro_tts as local
    monkeypatch.setattr(tts, "TTS_CACHE_DIR", tmp_path / "cache")
    calls = []
    async def synth(text, output_path, voice, rate, volume, pitch):
        calls.append(voice)
        from pathlib import Path
        Path(output_path).write_bytes(b"local audio")
        return TTSResult(output_path, 1.25, [WordTiming("Hello", .12, .83)])
    monkeypatch.setattr(local, "generate_local_speech", synth)
    first = await tts.generate_speech_with_timings("Hello", str(tmp_path / "one.mp3"), voice="kokoro:af_heart")
    second = await tts.generate_speech_with_timings("Hello", str(tmp_path / "two.mp3"), voice="kokoro:af_heart")
    assert calls == ["kokoro:af_heart"]
    assert first.words == second.words == [WordTiming("Hello", .12, .83)]
    assert second.duration == 1.25


def test_local_voices_have_distinct_valid_ids():
    assert len({voice["id"] for voice in VOICES}) == len(VOICES)
    assert all(voice["id"].startswith("kokoro:") for voice in VOICES)


@pytest.mark.asyncio
async def test_online_voice_timeout_keeps_local_voices_available(monkeypatch):
    import app as server
    async def unavailable(**kwargs):
        raise asyncio.TimeoutError()
    monkeypatch.setattr(server, "get_available_voices", unavailable)
    response = await server.list_voices()
    assert any(voice["id"] == "kokoro:af_heart" for voice in response["voices"])
    assert any(voice["id"] == "en-US-ChristopherNeural" for voice in response["voices"])


def test_cached_model_files_do_not_make_network_requests(monkeypatch):
    from core.kokoro_tts import model_file
    import sys
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        return "cached-model.pth"
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", SimpleNamespace(LocalEntryNotFoundError=FileNotFoundError))
    assert model_file("kokoro-v1_0.pth") == "cached-model.pth"
    assert len(calls) == 1 and calls[0]["local_files_only"] is True


def test_uncached_model_file_downloads_once(monkeypatch):
    from core.kokoro_tts import model_file
    import sys
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        if kwargs.get("local_files_only"):
            raise FileNotFoundError()
        return "new-voice.pt"
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(hf_hub_download=download))
    monkeypatch.setitem(sys.modules, "huggingface_hub.errors", SimpleNamespace(LocalEntryNotFoundError=FileNotFoundError))
    assert model_file("voices/af_bella.pt") == "new-voice.pt"
    assert len(calls) == 2 and "local_files_only" not in calls[1]
