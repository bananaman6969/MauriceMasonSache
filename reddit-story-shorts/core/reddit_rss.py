"""Fetch public Reddit Atom feeds, with a bounded local cache."""
import copy
import hashlib
import json
import logging
from html.parser import HTMLParser
from email.utils import parsedate_to_datetime
from pathlib import Path
import re
import threading
import time
import uuid
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

import requests

CACHE_DIR = Path(__file__).resolve().parents[1] / "cache" / "reddit"
TTL = 300
MAX_STALE = 6 * 3600
NS = {"a": "http://www.w3.org/2005/Atom"}
_lock = threading.Lock()
_retry_at = 0.0
_last_request_at = 0.0
_throttle_loaded = False
_throttle_count = 0
_request_lock = threading.Lock()
logger = logging.getLogger(__name__)


def load_throttle():
    global _throttle_loaded, _retry_at, _throttle_count
    if _throttle_loaded:
        return
    _throttle_loaded = True
    try:
        state = json.loads((CACHE_DIR / "throttle.json").read_text())
        _retry_at = max(_retry_at, float(state["retry_at"]))
        _throttle_count = max(0, min(10, int(state["count"])))
    except (OSError, ValueError, KeyError, TypeError):
        pass


def save_throttle():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "throttle.json"
    temp = path.with_name(f"throttle_{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps({"retry_at": _retry_at, "count": _throttle_count}))
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def retry_delay(header, count):
    """Honor either Retry-After form; use increasing backoff if it is absent."""
    fallback = min(3600, 300 * 2 ** min(max(count - 1, 0), 4))
    if header:
        try:
            return max(60, int(header))
        except ValueError:
            try:
                return max(60, parsedate_to_datetime(header).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                pass
    return fallback


class StoryHTML(HTMLParser):
    """Extract only the story div, excluding feed footer links and usernames."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.parts = []
        self.suppressed = 0

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            if self.depth or "md" in dict(attrs).get("class", "").split():
                self.depth += 1
        if self.depth:
            if tag in ("script", "style"):
                self.suppressed += 1
            if tag in ("p", "br", "li", "blockquote"):
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if self.depth and tag in ("script", "style"):
            self.suppressed = max(0, self.suppressed - 1)
        if self.depth and tag in ("p", "li", "blockquote"):
            self.parts.append("\n")
        if tag == "div" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and not self.suppressed:
            self.parts.append(data)


def parse_feed(xml, subreddit, post_id=None):
    from core.scraper import parse_post_dict
    root = ET.fromstring(xml)
    if root.tag != f"{{{NS['a']}}}feed":
        raise ValueError("Reddit returned an unexpected feed format")
    posts, seen = [], set()
    for entry in root.findall("a:entry", NS):
        identifier = entry.findtext("a:id", "", NS)
        if not identifier.startswith("t3_"):
            continue  # Comments are not standalone story posts.
        identifier = identifier[3:]
        if identifier in seen or (post_id and identifier != post_id):
            continue
        category = entry.find("a:category", NS)
        entry_sub = category.get("term", subreddit) if category is not None else subreddit
        if entry_sub.lower() != subreddit.lower():
            continue
        author = entry.findtext("a:author/a:name", "[deleted]", NS).removeprefix("/u/")
        if author.lower() in ("automoderator", "aitamod"):
            continue
        link = entry.find("a:link", NS)
        url = link.get("href", "") if link is not None else ""
        parsed_url = urlparse(url)
        if parsed_url.scheme != "https" or parsed_url.hostname not in ("reddit.com", "www.reddit.com", "old.reddit.com"):
            continue
        extractor = StoryHTML()
        extractor.feed(entry.findtext("a:content", "", NS))
        body = "".join(extractor.parts).strip()
        if body.lower() in ("[removed]", "[deleted]"):
            continue
        if not body and subreddit.lower() != "askreddit":
            continue
        post = parse_post_dict({"id": identifier, "title": entry.findtext("a:title", "", NS),
            "selftext": body, "author": author, "subreddit": entry_sub,
            "permalink": parsed_url.path, "url": url})
        if post:
            post.update(source="reddit_rss", score=None, num_comments=None,
                published_at=entry.findtext("a:published", "", NS), needs_body=not bool(body))
            seen.add(identifier)
            posts.append(post)
    return posts


def validate_options(subreddit, sort, timeframe, limit):
    sub = re.sub(r"^/?r/", "", subreddit.strip(), flags=re.I)
    if not re.fullmatch(r"[A-Za-z0-9_]{2,21}", sub):
        raise ValueError("Invalid subreddit name")
    if sort == "top_week":
        sort, timeframe = "top", "week"
    if sort not in ("hot", "top", "new") or timeframe not in ("hour", "day", "week", "month", "year", "all"):
        raise ValueError("Invalid Reddit sort or timeframe")
    if not 1 <= limit <= 100:
        raise ValueError("Story limit must be between 1 and 100")
    return sub, sort, timeframe


def fetch_feed(url, params, subreddit, post_id=None):
    global _retry_at, _last_request_at, _throttle_count
    with _request_lock:
        load_throttle()
        if time.time() < _retry_at:
            raise ValueError("Reddit requested a pause before the next refresh")
        delay = max(0, 5 - (time.monotonic() - _last_request_at))
        if delay:
            time.sleep(delay)
        _last_request_at = time.monotonic()
        response = requests.get(url, params=params,
            headers={"User-Agent": "RedditStoryShorts/1.0 (local story dashboard)",
                     "Accept": "application/atom+xml, application/xml"}, timeout=(5, 15))
        if response.status_code == 429:
            _throttle_count += 1
            _retry_at = time.time() + retry_delay(response.headers.get("Retry-After"), _throttle_count)
            save_throttle()
        response.raise_for_status()
        if _throttle_count:
            _throttle_count = 0
            _retry_at = 0
            save_throttle()
    if len(response.content) > 2_000_000:
        raise ValueError("Reddit feed exceeds the size limit")
    return parse_feed(response.content, subreddit, post_id)


def get_listing(subreddit, sort="hot", timeframe="day", limit=25):
    sub, sort, timeframe = validate_options(subreddit, sort, timeframe, limit)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(repr([sub.lower(), sort, timeframe]).encode()).hexdigest()
    path = CACHE_DIR / f"{key}.json"
    with _lock:
        cached = None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(cached["posts"], list) or not isinstance(cached["fetched_at"], (float, int)):
                cached = None
        except (OSError, ValueError, KeyError, TypeError):
            pass
        age = time.time() - cached["fetched_at"] if cached else float("inf")
        if cached and 0 <= age < TTL:
            return _result(cached, limit, "cached_rss")
        try:
            # Fetch a modest batch rather than 100 posts on every cache miss.
            params = {"limit": min(limit, 50)}
            if sort == "top":
                params["t"] = timeframe
            posts = fetch_feed(f"https://www.reddit.com/r/{sub}/{sort}/.rss", params, sub)
            fresh = {"posts": posts, "fetched_at": time.time(), "subreddit": sub,
                "sort": sort, "timeframe": timeframe}
            temp = path.with_name(f"{key}_{uuid.uuid4().hex}.tmp")
            try:
                temp.write_text(json.dumps(fresh), encoding="utf-8")
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
            return _result(fresh, limit, "reddit_rss")
        except (requests.RequestException, ValueError, ET.ParseError) as error:
            logger.warning("Reddit RSS refresh failed for r/%s: %s", sub, error)
            if cached and 0 <= age < MAX_STALE:
                return _result(cached, limit, "cached_rss", stale=True,
                    message="Reddit refresh failed. Showing previously fetched posts.")
            # A different sort for the same subreddit is still useful, but label it explicitly.
            alternatives = []
            for candidate in CACHE_DIR.glob("*.json"):
                if candidate.name == "throttle.json" or candidate == path:
                    continue
                try:
                    other = json.loads(candidate.read_text(encoding="utf-8"))
                    if (0 <= time.time() - other["fetched_at"] < MAX_STALE and other["posts"]
                        and all(p["subreddit"].lower() == f"r/{sub.lower()}" for p in other["posts"])):
                        alternatives.append(other)
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            if alternatives:
                other = max(alternatives, key=lambda item: item["fetched_at"])
                result = _result(other, limit, "cached_rss", stale=True,
                    message="Requested feed is unavailable. Showing previously fetched posts from this subreddit; the requested sort may differ.")
                result["fallback_sort"] = True
                return result
            message = ("Reddit is rate limiting requests. Please wait a few minutes before refreshing."
                if time.time() < _retry_at else
                "Reddit RSS is unavailable. Try again later or paste a story into the editor.")
            return {"posts": [], "source": "unavailable", "fetched_at": None,
                "stale": False, "message": message,
                "retry_at": _retry_at if _retry_at > time.time() else None}


def _result(data, limit, source, stale=False, message=None):
    posts = copy.deepcopy(data["posts"][:limit])
    for post in posts:
        post["source"] = source
    return {"posts": posts, "source": source, "fetched_at": data["fetched_at"],
        "stale": stale, "message": message,
        "retry_at": _retry_at if _retry_at > time.time() else None}
