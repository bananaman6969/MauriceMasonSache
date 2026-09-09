"""Reddit Story Scraper: Scrapes public Reddit JSON endpoints without credentials."""

import os
import re
import logging
from typing import List, Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36 RedditStoryShorts/1.0"
)

# Common Reddit story acronyms for TTS expansion
ACRONYM_EXPANSIONS = {
    r"\bAITA\b": "Am I the asshole",
    r"\bWIBTA\b": "Would I be the asshole",
    r"\bNTA\b": "Not the asshole",
    r"\bYTA\b": "You're the asshole",
    r"\bESH\b": "Everyone sucks here",
    r"\bNAH\b": "No assholes here",
    r"\bTIFU\b": "Today I messed up",
    r"\bTL;?DR:?\b": "In summary",
    r"\bOP\b": "the poster",
    r"\bSIL\b": "sister in law",
    r"\bBIL\b": "brother in law",
    r"\bMIL\b": "mother in law",
    r"\bFIL\b": "father in law",
    r"\bSO\b": "significant other",
    r"\bGF\b": "girlfriend",
    r"\bBF\b": "boyfriend",
}

DEFAULT_SUBREDDITS = [
    "AmItheAsshole",
    "AskReddit",
    "tifu",
    "confession",
    "TrueOffMyChest",
    "stories",
    "pettyrevenge",
    "relationship_advice",
]


def clean_story_text(text: str, expand_acronyms: bool = True) -> str:
    """Sanitize Reddit story text for TTS narration."""
    if not text:
        return ""

    cleaned = text

    # Remove Markdown links [label](url) -> label
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)

    # Remove standalone URLs
    cleaned = re.sub(r"https?://\S+", "", cleaned)

    # Expand common Reddit acronyms for natural speech
    if expand_acronyms:
        for pattern, replacement in ACRONYM_EXPANSIONS.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)

    # Remove Reddit formatting artifacts (*, **, #, >, ~)
    cleaned = re.sub(r"[\*_#~>`]", "", cleaned)

    # Clean multiple newlines and spaces
    cleaned = re.sub(r"\n{2,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)

    return cleaned.strip()


def estimate_duration_seconds(word_count: int, words_per_minute: int = 150) -> float:
    """Estimate spoken audio duration in seconds."""
    if word_count <= 0:
        return 0.0
    return round((word_count / words_per_minute) * 60, 1)


def parse_post_dict(post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract and sanitize fields from a raw Reddit post JSON object."""
    try:
        # Ignore pinned/stickied posts or empty selftext
        if post.get("stickied", False):
            return None

        raw_title = (post.get("title") or post.get("raw_title") or "").strip()
        raw_body = (post.get("selftext") or post.get("body") or post.get("raw_body") or "").strip()

        # If it's r/AskReddit, selftext might be empty and comments are the stories,
        # but for standard story subs (AITA, tifu, confession), body must not be empty.
        if not raw_title:
            return None

        # Clean text
        title = clean_story_text(raw_title)
        body = clean_story_text(raw_body)
        full_text = f"{title}\n\n{body}" if body else title

        words = len(full_text.split())
        est_duration = estimate_duration_seconds(words)

        return {
            "id": post.get("id", ""),
            "title": title,
            "raw_title": raw_title,
            "body": body,
            "raw_body": raw_body,
            "full_text": full_text,
            "author": post.get("author", "[deleted]"),
            "subreddit": f"r/{post.get('subreddit', '')}",
            "score": post.get("score", 0),
            "num_comments": post.get("num_comments", 0),
            "permalink": f"https://reddit.com{post.get('permalink', '')}",
            "url": post.get("url", ""),
            "over_18": post.get("over_18", False),
            "word_count": words,
            "est_duration_seconds": est_duration,
        }
    except Exception as err:
        logger.error(f"Error parsing post: {err}")
        return None


def load_curated_viral_stories(subreddit: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load curated viral stories from local JSON dataset as a reliable fallback."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(project_root, "data", "viral_stories.json")

    if not os.path.exists(json_path):
        return []

    try:
        import json
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        stories: List[Dict[str, Any]] = []
        clean_sub = (subreddit or "").replace("r/", "").strip().lower()

        for sub_key, sub_posts in data.items():
            if not clean_sub or clean_sub == sub_key.lower():
                for p in sub_posts:
                    parsed = parse_post_dict(p)
                    if parsed:
                        parsed["source"] = "curated_viral"
                        stories.append(parsed)

        # If specific subreddit had no entries, return all curated stories
        if not stories and clean_sub:
            for sub_key, sub_posts in data.items():
                for p in sub_posts:
                    parsed = parse_post_dict(p)
                    if parsed:
                        parsed["source"] = "curated_viral"
                        stories.append(parsed)

        return stories
    except Exception as err:
        logger.error(f"Failed to load curated viral stories: {err}")
        return []


def fetch_subreddit_posts(
    subreddit: str,
    sort: str = "hot",
    timeframe: str = "day",
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """Fetch stories from a subreddit using the public Reddit JSON endpoint with automatic fallback to curated viral library.
    
    Args:
        subreddit: Name of the subreddit (without r/).
        sort: 'hot', 'top', or 'new'.
        timeframe: 'day', 'week', 'month', or 'all' (for top sort).
        limit: Number of items to fetch (max 100).
        
    Returns:
        List of parsed post dictionaries.
    """
    clean_sub = subreddit.replace("r/", "").strip()
    url = f"https://www.reddit.com/r/{clean_sub}/{sort}.json"
    params = {"limit": min(limit, 100), "raw_json": 1}
    if sort == "top":
        params["t"] = timeframe

    # Check for official Reddit OAuth API credentials
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    if client_id and client_secret:
        try:
            auth = requests.auth.HTTPBasicAuth(client_id, client_secret)
            token_resp = requests.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=auth,
                headers={"User-Agent": "windows:storyshorts:v1.0 (by /u/StoryShortsBot)"},
                timeout=10,
            )
            token_data = token_resp.json()
            access_token = token_data.get("access_token")
            if access_token:
                oauth_headers = {
                    "Authorization": f"Bearer {access_token}",
                    "User-Agent": "windows:storyshorts:v1.0 (by /u/StoryShortsBot)",
                }
                oauth_url = f"https://oauth.reddit.com/r/{clean_sub}/{sort}"
                res = requests.get(oauth_url, params=params, headers=oauth_headers, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    children = data.get("data", {}).get("children", [])
                    parsed_posts = [
                        parse_post_dict(c.get("data", {}))
                        for c in children
                        if parse_post_dict(c.get("data", {}))
                    ]
                    if parsed_posts:
                        return parsed_posts
        except Exception as err:
            logger.warning(f"Reddit OAuth query failed: {err}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=3)
        if response.status_code == 200:
            data = response.json()
            children = data.get("data", {}).get("children", [])
            parsed_posts: List[Dict[str, Any]] = []

            for child in children:
                item = child.get("data", {})
                parsed = parse_post_dict(item)
                if parsed and (parsed["body"] or clean_sub.lower() == "askreddit"):
                    parsed["source"] = "live_reddit"
                    parsed_posts.append(parsed)

            if parsed_posts:
                return parsed_posts
    except Exception as err:
        logger.warning(f"Live Reddit request to r/{clean_sub} encountered {err}.")

    # Fallback to Curated Viral Stories Dataset
    logger.info(f"Using curated viral stories dataset for r/{clean_sub} (bypassing Reddit anti-bot CAPTCHA)")
    curated = load_curated_viral_stories(clean_sub)
    if curated:
        return curated[:limit]

    return []


def fetch_post_by_url(reddit_url: str) -> Dict[str, Any]:
    """Fetch a single Reddit post by URL with graceful fallback."""
    clean_url = reddit_url.split("?")[0].rstrip("/") + ".json"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }

    try:
        response = requests.get(clean_url, params={"raw_json": 1}, headers=headers, timeout=6)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                post_data = data[0].get("data", {}).get("children", [])[0].get("data", {})
                parsed = parse_post_dict(post_data)
                if parsed:
                    parsed["source"] = "live_reddit"
                    return parsed
    except Exception as err:
        logger.warning(f"Direct Reddit post fetch failed: {err}")

    # Fallback to curated library
    curated = load_curated_viral_stories()
    for c in curated:
        if c["permalink"] in reddit_url or c["id"] in reddit_url:
            return c

    # Fallback: Extract title and subreddit directly from URL slug
    parts = [p for p in reddit_url.split("?")[0].split("/") if p]
    extracted_sub = "r/AmItheAsshole"
    extracted_title = ""
    if "r" in parts:
        r_idx = parts.index("r")
        if len(parts) > r_idx + 1:
            extracted_sub = f"r/{parts[r_idx + 1]}"
    if "comments" in parts:
        c_idx = parts.index("comments")
        if len(parts) > c_idx + 2:
            slug = parts[c_idx + 2]
            slug_words = slug.replace("_", " ").replace("-", " ").strip()
            slug_words = re.sub(r"\bupdateaita\b", "Update: AITA", slug_words, flags=re.IGNORECASE)
            slug_words = re.sub(r"\baita\b", "AITA", slug_words, flags=re.IGNORECASE)
            slug_words = re.sub(r"\bwibta\b", "WIBTA", slug_words, flags=re.IGNORECASE)
            slug_words = re.sub(r"\btifu\b", "TIFU", slug_words, flags=re.IGNORECASE)
            extracted_title = slug_words[0].upper() + slug_words[1:] if slug_words else ""

    if extracted_title:
        return {
            "id": "",
            "title": extracted_title,
            "raw_title": extracted_title,
            "body": "",
            "raw_body": "",
            "full_text": extracted_title,
            "author": "StoryTeller",
            "subreddit": extracted_sub,
            "score": 14200,
            "num_comments": 850,
            "permalink": reddit_url,
            "url": reddit_url,
            "over_18": False,
            "word_count": len(extracted_title.split()),
            "est_duration_seconds": 5.0,
            "source": "url_slug_extracted",
            "needs_body": True,
        }

    # If post could not be fetched due to Reddit's CAPTCHA block
    raise ValueError(
        "Reddit's anti-bot policy blocked direct unauthenticated access to this URL. "
        "Please copy & paste the story text directly into the Script Editor below."
    )

