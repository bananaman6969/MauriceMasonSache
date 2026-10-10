import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uploader import Queue, ProviderError, UploadPost, load_config, outcome, work_once, worker_lock

spec = importlib.util.spec_from_file_location("upload_handoff", ROOT.parent / "reddit-story-shorts/core/upload_handoff.py")
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class FakeProvider:
    def __init__(self, submit=None, status=None):
        self.submit_response = submit or {"request_id": "remote-1", "status": "pending"}
        self.status_response = status or {"status": "completed", "results": [
            {"platform": "tiktok", "success": True, "post_url": "https://example.com/post"}]}
        self.calls = []

    def submit(self, job, profile):
        self.calls.append(("submit", job["id"], profile["user"]))
        if isinstance(self.submit_response, Exception):
            raise self.submit_response
        return self.submit_response

    def status(self, request_id):
        self.calls.append(("status", request_id))
        return self.status_response


class PipelineTests(unittest.TestCase):
    def setUp(self):
        temp_root = ROOT / ".pytest_temp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.root = Path(self.temp.name)
        self.config = {"watch_directories": [self.root], "profiles": {
            "stories": {"user": "account-1", "privacy_level": "SELF_ONLY", "min_interval_seconds": 60},
            "other": {"user": "account-2", "privacy_level": "SELF_ONLY", "min_interval_seconds": 60}}}
        self.db = self.root / "data" / "uploads.sqlite3"
        self.queue = Queue(self.db)

    def tearDown(self):
        self.queue.db.close()
        self.temp.cleanup()

    def video(self, name="clip", profile="stories", content=b"test video"):
        (self.root / f"{name}.mp4").write_bytes(content)
        (self.root / f"{name}.post.json").write_text(json.dumps({
            "video": f"{name}.mp4", "profile": profile, "title": "Caption", "is_aigc": True}))

    def test_dedup_survives_restart_and_rename_but_routes_to_other_account(self):
        self.video()
        self.assertEqual(self.queue.scan(self.config), 1)
        self.queue.db.close()
        self.queue = Queue(self.db)
        self.video("renamed")
        self.video("other", "other")
        self.assertEqual(self.queue.scan(self.config), 1)
        self.assertEqual(len(self.queue.rows()), 2)

    def test_ignore_partial_handoff_and_unmarked_videos(self):
        (self.root / "clip.mp4").write_bytes(b"unfinished")
        (self.root / "clip.post.json.tmp").write_text("{")
        self.assertEqual(self.queue.scan(self.config), 0)

    def test_handoff_is_optional_atomic_and_keeps_caption(self):
        (self.root / "clip.mp4").write_bytes(b"video")
        with patch.dict(os.environ, {"TIKTOK_UPLOAD_PROFILE": ""}):
            self.assertFalse(handoff.handoff_video(str(self.root), "clip.mp4", "Title"))
        with patch.dict(os.environ, {"TIKTOK_UPLOAD_PROFILE": "stories"}):
            self.assertTrue(handoff.handoff_video(str(self.root), "clip.mp4", "Caption 🌍"))
        self.assertEqual(self.queue.scan(self.config), 1)
        self.assertEqual(self.queue.rows()[0]["title"], "Caption 🌍")
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_upload_then_poll_confirmed_post(self):
        self.video()
        self.queue.scan(self.config)
        provider = FakeProvider()
        work_once(self.queue, self.config, provider, now=100)
        self.assertEqual(self.queue.rows()[0]["status"], "processing")
        work_once(self.queue, self.config, provider, now=116)
        self.assertEqual(self.queue.rows()[0]["status"], "published")
        self.assertEqual(provider.calls[1], ("status", "remote-1"))
        self.assertFalse(work_once(self.queue, self.config, provider, now=200))

    def test_timeout_reconciles_without_resubmission(self):
        self.video()
        self.queue.scan(self.config)
        provider = FakeProvider(submit=ProviderError("Network failure", transient=True, uncertain=True))
        work_once(self.queue, self.config, provider, now=100)
        self.assertEqual(self.queue.rows()[0]["status"], "checking")
        work_once(self.queue, self.config, provider, now=161)
        self.assertEqual([call[0] for call in provider.calls], ["submit", "status"])
        self.assertEqual(self.queue.rows()[0]["status"], "published")

    def test_crashed_inflight_submission_is_polled(self):
        self.video()
        self.queue.scan(self.config)
        self.queue.claim(self.config, 100)
        provider = FakeProvider(status={"status": "not_found"})
        self.assertFalse(work_once(self.queue, self.config, provider, now=999))
        work_once(self.queue, self.config, provider, now=1001)
        self.assertEqual(provider.calls[0][0], "status")
        self.assertEqual(self.queue.rows()[0]["status"], "needs_action")

    def test_rate_limit_retry_and_per_account_spacing(self):
        self.video()
        self.video("second", content=b"another video")
        self.queue.scan(self.config)
        provider = FakeProvider(submit=ProviderError("Provider HTTP 429", transient=True))
        work_once(self.queue, self.config, provider, now=100)
        self.assertEqual(self.queue.rows()[0]["status"], "retry")
        self.assertFalse(work_once(self.queue, self.config, provider, now=120))
        work_once(self.queue, self.config, provider, now=161)
        self.assertEqual(provider.calls[0][1], provider.calls[1][1])

    def test_changed_media_not_uploaded(self):
        self.video()
        self.queue.scan(self.config)
        (self.root / "clip.mp4").write_bytes(b"changed")
        provider = FakeProvider()
        work_once(self.queue, self.config, provider, now=100)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.queue.rows()[0]["status"], "needs_action")

    def test_worker_exclusion(self):
        with worker_lock(self.db):
            with self.assertRaises(ValueError):
                with worker_lock(self.db):
                    pass

    def test_unconnected_inbox_and_empty_completion_not_published(self):
        cases = [
            ({"status": "completed", "results": [{"platform": "tiktok", "skipped": True}]}, "failed"),
            ({"status": "completed", "results": [{"platform": "tiktok", "success": True, "fallback_to_inbox": True}]}, "needs_action"),
            ({"status": "completed", "results": []}, "needs_action"),
            ({"success": True, "request_id": "remote"}, "processing"),
            ({"status": "failed", "results": []}, "failed"),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(outcome(payload)[0], expected)

    def test_config_requires_explicit_privacy(self):
        config = self.root / "config.json"
        config.write_text(json.dumps({"watch_directories": ["."], "profiles": {"a": {"user": "a"}}}))
        with self.assertRaises(ValueError):
            load_config(config)

    def test_manifest_cannot_escape_watch_directory(self):
        (self.root / "bad.post.json").write_text(json.dumps({"video": "../outside.mp4", "profile": "stories", "title": "test"}))
        self.assertEqual(self.queue.scan(self.config), 0)

    def test_provider_sends_account_privacy_file_and_idempotency_key(self):
        self.video()
        self.queue.scan(self.config)
        session = Mock()
        session.request.return_value.status_code = 202
        session.request.return_value.json.return_value = {"request_id": "remote", "status": "pending"}
        provider = UploadPost("test-secret", session=session)
        job = self.queue.rows()[0]
        provider.submit(job, self.config["profiles"]["stories"])
        args, options = session.request.call_args
        self.assertEqual(args, ("POST", "https://api.upload-post.com/api/upload"))
        self.assertEqual(options["headers"]["Idempotency-Key"], job["id"])
        self.assertEqual(options["data"]["request_id"], job["id"])
        self.assertEqual(options["data"]["user"], "account-1")
        self.assertEqual(options["data"]["privacy_level"], "SELF_ONLY")
        self.assertEqual(options["data"]["disable_inbox_fallback"], "true")
        self.assertEqual(options["data"]["is_aigc"], "true")
        self.assertTrue(options["files"]["video"][1].closed)

    def test_provider_timeout_does_not_expose_key(self):
        import requests
        session = Mock()
        session.request.side_effect = requests.Timeout("secret request body")
        provider = UploadPost("test-secret", session=session)
        with self.assertRaises(ProviderError) as caught:
            provider.request("POST", "/upload")
        self.assertTrue(caught.exception.uncertain)
        self.assertNotIn("secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
