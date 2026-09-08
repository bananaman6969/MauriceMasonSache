"""Tests for FastAPI endpoints."""

import pytest
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)


def test_index_page():
    response = client.get("/")
    assert response.status_code == 200
    assert "Reddit Story" in response.text
    assert "Script Editor" in response.text


def test_get_subreddits():
    response = client.get("/api/subreddits")
    assert response.status_code == 200
    data = response.json()
    assert "subreddits" in data
    assert "AmItheAsshole" in data["subreddits"]


def test_get_voices():
    response = client.get("/api/voices")
    assert response.status_code == 200
    data = response.json()
    assert "voices" in data
    assert len(data["voices"]) > 0


def test_get_gameplay_list():
    response = client.get("/api/gameplay/list")
    assert response.status_code == 200
    data = response.json()
    assert "videos" in data
    assert "presets" in data


def test_split_story_api():
    payload = {
        "title": "AITA for saying no?",
        "body": "This is a simple short story for testing the split endpoint.",
        "max_duration_seconds": 60,
    }
    response = client.post("/api/split-story", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "parts" in data
    assert len(data["parts"]) == 1


def test_list_videos_api():
    response = client.get("/api/videos")
    assert response.status_code == 200
    data = response.json()
    assert "videos" in data


def test_reddit_posts_have_body():
    response = client.get("/api/reddit/posts?subreddit=AmItheAsshole&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert len(data["posts"]) > 0
    # Every post must have a non-empty body
    for p in data["posts"]:
        assert "body" in p
        assert len(p["body"].strip()) > 0
        assert "title" in p
        assert len(p["title"].strip()) > 0


def test_cancel_render_job_endpoint():
    # Calling cancel on a job id
    response = client.post("/api/render/cancel/test_job_123")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "stopped" in data["message"].lower()

