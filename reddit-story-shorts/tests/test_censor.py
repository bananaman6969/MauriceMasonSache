import asyncio
import pytest
from fastapi.testclient import TestClient
from core.censor import censor_text, prepare_story, narration_text, caption_words, REPLACEMENTS
from core.tts import WordTiming
import app as server


@pytest.mark.parametrize("word", ["raped", "RAPE", "raping", "rapists", "murder", "murdered", "murderers", "fucking", "asshole"])
def test_target_words(word):
    assert censor_text(f"He said {word}.") == f"He said {REPLACEMENTS[word.lower()][0]}."


def test_whole_words_and_opt_out():
    text = "grape scraped assignment murder mystery"
    assert censor_text(text) == "grape scraped assignment unaliving mystery"
    assert prepare_story("Murder", "He was raped.", False) == ("Murder", "He was raped.")


def test_script_and_split_preview():
    client = TestClient(server.app)
    payload = {"title": "Murder story", "body": "He was raped.", "censor_words": True}
    preview = client.post("/api/story/censor-preview", json=payload)
    assert preview.json() == {"title": "unaliving story", "body": "He was gr*ped."}
    part = client.post("/api/split-story", json=payload).json()["parts"][0]
    assert part["part_title"] == "unaliving story"
    assert part["script"] == "unaliving story. He was gr*ped."


def test_voice_preview_uses_censored_text(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "TEMP_DIR", str(tmp_path))
    seen = []
    async def speech(**kwargs):
        seen.append(kwargs["text"])
    monkeypatch.setattr(server, "generate_speech_with_timings", speech)
    response = TestClient(server.app).post("/api/tts/preview", json={"text": "Murder and rape", "censor_words": True})
    assert response.status_code == 200
    assert seen == ["unaliving and grape"]


def test_render_censors_before_splitting_without_mutating_original(monkeypatch):
    seen = []
    def split(**kwargs):
        seen.append((kwargs["title"], kwargs["body"]))
        raise RuntimeError("Stop before media generation")
    monkeypatch.setattr(server, "split_story_into_parts", split)
    request = server.RenderJobRequest(title="Murder story", body="He was raped.", censor_words=True, split_parts=True)
    server.render_jobs["censor-test"] = {}
    try:
        asyncio.run(server._run_render_job("censor-test", request))
        assert seen == [("unaliving story", "He was gr*ped.")]
        assert request.title == "Murder story" and request.body == "He was raped."
    finally:
        server.render_jobs.pop("censor-test", None)


def test_narration_and_caption_alignment_preserves_timing_and_normal_words():
    script = "A grape. He was gr*ped and f*cking furious."
    assert narration_text(script) == "A grape. He was graped and effing furious."
    words = [WordTiming(word, i * .2, i * .2 + .2) for i, word in enumerate(narration_text(script).split())]
    result = caption_words(words, script)
    assert [w.word for w in result] == ["A", "grape.", "He", "was", "gr*ped", "and", "f*cking", "furious."]
    assert [(w.start, w.end) for w in result] == [(w.start, w.end) for w in words]
    assert words[4].word == "graped"


def test_censoring_is_idempotent():
    text = censor_text("raped, murdered, asshole")
    assert censor_text(text) == text
