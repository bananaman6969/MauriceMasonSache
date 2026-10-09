import json
import time
import requests
import pytest
from core import reddit_rss as rss
from core.scraper import fetch_subreddit_posts, load_curated_viral_stories
from core.title_card import format_score

def feed(body="A &amp; B tell a story.", sub="tifu", author="writer", identifier="t3_abc"):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>{identifier}</id><title>A fresh story</title><author><name>/u/{author}</name></author>
        <category term="{sub}"/><link href="https://www.reddit.com/r/{sub}/comments/abc/story/"/>
        <published>2026-10-09T12:00:00+00:00</published>
        <content type="html">&lt;div class="md"&gt;&lt;p&gt;{body}&lt;/p&gt;&lt;/div&gt; submitted by writer [comments]</content>
        </entry></feed>'''

@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(rss, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(rss, "_retry_at", 0)
    monkeypatch.setattr(rss, "_last_request_at", 0)
    monkeypatch.setattr(rss, "_throttle_loaded", False)
    monkeypatch.setattr(rss, "_throttle_count", 0)

def test_extract_body_without_footer_and_unknown_scores():
    post = rss.parse_feed(feed(), "tifu")[0]
    assert post["body"] == "A & B tell a story."
    assert post["score"] is None and post["num_comments"] is None
    assert post["author"] == "writer" and post["source"] == "reddit_rss"
    assert format_score(None) == "—"

def test_deduplicate_filter_removed_bots_and_wrong_subreddit():
    xml = feed()
    entry = xml[xml.index("<entry>"):xml.index("</entry>") + len("</entry>")]
    assert len(rss.parse_feed(xml.replace("</feed>", entry + "</feed>"), "tifu")) == 1
    assert not rss.parse_feed(feed("[removed]"), "tifu")
    assert not rss.parse_feed(feed(author="AutoModerator"), "tifu")
    assert not rss.parse_feed(feed(sub="stories"), "tifu")
    assert not rss.parse_feed(feed(identifier="t1_comment"), "tifu")

def test_askreddit_empty_question_is_explicit():
    post = rss.parse_feed(feed(body="", sub="AskReddit"), "AskReddit")[0]
    assert post["needs_body"] and not post["body"]
    assert not rss.parse_feed(feed(body=""), "tifu")

def test_cache_limit_top_week_and_no_api_calls(monkeypatch):
    calls = []
    class Response:
        status_code = 200
        content = feed().encode()
        def raise_for_status(self): pass
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response()
    monkeypatch.setattr(rss.requests, "get", get)
    first = rss.get_listing("r/tifu", "top_week", limit=1)
    second = rss.get_listing("tifu", "top", "week", 5)
    assert first["source"] == "reddit_rss" and second["source"] == "cached_rss"
    assert len(calls) == 1 and calls[0][0].endswith("/top/.rss")
    assert calls[0][1]["params"]["t"] == "week"
    assert calls[0][1]["params"]["limit"] != 100
    assert fetch_subreddit_posts("tifu", "top", "week", 1)[0]["body"]

def test_stale_cache_and_failure_never_replace_with_curated(monkeypatch):
    monkeypatch.setattr(rss, "fetch_feed", lambda *a: rss.parse_feed(feed(), "tifu"))
    rss.get_listing("tifu")
    path = next(rss.CACHE_DIR.glob("*.json"))
    data = json.loads(path.read_text())
    data["fetched_at"] = time.time() - 600
    path.write_text(json.dumps(data))
    def fail(*args): raise requests.ConnectionError("Offline")
    monkeypatch.setattr(rss, "fetch_feed", fail)
    assert rss.get_listing("tifu")["stale"] is True
    data["fetched_at"] = time.time() - rss.MAX_STALE - 1
    path.write_text(json.dumps(data))
    assert rss.get_listing("tifu")["posts"] == []
    assert load_curated_viral_stories("no_such_curated_sub") == []

def test_rate_limit_is_respected(monkeypatch):
    calls = []
    class Response:
        status_code = 429
        headers = {"Retry-After": "60"}
        def raise_for_status(self): raise requests.HTTPError("429")
    monkeypatch.setattr(rss.requests, "get", lambda *a, **kw: (calls.append(1) or Response()))
    assert rss.get_listing("tifu")["source"] == "unavailable"
    assert rss.get_listing("stories")["source"] == "unavailable"
    assert len(calls) == 1
    assert rss.get_listing("stories")["retry_at"] > time.time()
    monkeypatch.setattr(rss, "_throttle_loaded", False)
    monkeypatch.setattr(rss, "_retry_at", 0)
    rss.get_listing("confession")
    assert len(calls) == 1  # Restarting does not reset Reddit's cooldown.

def test_retry_after_date_and_increasing_backoff():
    from email.utils import formatdate
    assert rss.retry_delay("7200", 1) == 7200
    assert 110 <= rss.retry_delay(formatdate(time.time() + 120, usegmt=True), 1) <= 120
    assert rss.retry_delay(None, 2) == 600

def test_other_sort_cache_is_available_during_throttle(monkeypatch):
    monkeypatch.setattr(rss, "fetch_feed", lambda *args: rss.parse_feed(feed(), "tifu"))
    rss.get_listing("tifu", "hot")
    def fail(*args):
        rss._retry_at = time.time() + 300
        raise ValueError("Cooldown")
    monkeypatch.setattr(rss, "fetch_feed", fail)
    result = rss.get_listing("tifu", "top")
    assert result["posts"] and result["fallback_sort"] and result["retry_at"]
    assert "sort may differ" in result["message"]

@pytest.mark.parametrize("sub,sort,limit", [("../../bad", "hot", 1), ("tifu", "bad", 1), ("tifu", "hot", 0)])
def test_invalid_options(sub, sort, limit):
    with pytest.raises(ValueError): rss.get_listing(sub, sort, limit=limit)

def test_invalid_html_is_not_accepted_as_feed():
    with pytest.raises(ValueError): rss.parse_feed("<html>login</html>", "tifu")
