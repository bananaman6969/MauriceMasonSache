"""Test FastAPI endpoints for Shorts Stealth Pipeline."""

import os
import pytest
from starlette.testclient import TestClient
from app import app, DB_PATH
import core.database as db


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_index_page(client):
    """Ensure homepage renders with 200 OK and contains UI elements."""
    response = client.get("/")
    assert response.status_code == 200
    assert "Shorts Stealth Pipeline" in response.text
    assert "Anti-Detection" in response.text
    assert "stopAllProcessing" in response.text


def test_stop_processing_endpoint(client):
    """Ensure stop processing endpoint halts pipeline and returns success."""
    response = client.post("/api/stop")
    assert response.status_code == 200
    data = response.json()
    assert data.get("success") is True
    assert "stopped" in data.get("message", "").lower()



def test_videos_catalog_endpoint(client):
    """Ensure catalog endpoint returns valid JSON structure."""
    response = client.get("/api/videos")
    assert response.status_code == 200
    data = response.json()
    assert "videos" in data
    assert isinstance(data["videos"], list)


@pytest.mark.asyncio
async def test_video_lifecycle_endpoints(client, tmp_path):
    """Test full cycle: insertion, retrieval, and deletion via API."""
    video_id = "test_lifecycle_vid"
    sample_file = tmp_path / "dummy.mp4"
    sample_file.write_bytes(b"dummy mp4 content")

    await db.upsert_discovered(DB_PATH, {
        "id": video_id,
        "title": "Lifecycle Test Video",
        "channel": "Tester",
        "views": 42000,
        "likes": 1337,
    })
    await db.mark_processed(
        DB_PATH,
        video_id,
        str(sample_file),
        {"speed": 1.02, "preset": "subtle"},
    )

    # Test stream
    stream_res = client.get(f"/api/stream/processed/{video_id}")
    assert stream_res.status_code == 200
    assert stream_res.content == b"dummy mp4 content"

    # Test download
    dl_res = client.get(f"/api/download/{video_id}")
    assert dl_res.status_code == 200
    assert dl_res.headers["content-disposition"].startswith("attachment")

    # Test delete
    del_res = client.delete(f"/api/videos/{video_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Confirm 404 after deletion
    assert client.get(f"/api/download/{video_id}").status_code == 404
