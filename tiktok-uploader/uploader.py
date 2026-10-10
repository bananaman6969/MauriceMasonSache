"""Durable TikTok upload queue. Network publishing uses Upload-Post."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

PRIVACY = {"SELF_ONLY", "PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR"}


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def load_config(path):
    config = json.loads(path.read_text(encoding="utf-8"))
    if not config.get("profiles") or not config.get("watch_directories"):
        raise ValueError("Configure profiles and watch_directories first")
    for profile in config["profiles"].values():
        if not profile.get("user") or profile["user"].startswith("YOUR_"):
            raise ValueError("Set each profile's Upload-Post user identifier")
        if profile.get("privacy_level") not in PRIVACY:
            raise ValueError("Each profile needs an explicit privacy_level")
        if float(profile.get("min_interval_seconds", 3600)) < 60:
            raise ValueError("min_interval_seconds must be at least 60")
    config["watch_directories"] = [(path.parent / p).resolve() for p in config["watch_directories"]]
    config["database"] = (path.parent / config.get("database", "data/uploads.sqlite3")).resolve()
    if float(config.get("poll_seconds", 15)) < 10:
        raise ValueError("poll_seconds must be at least 10")
    return config


class Queue:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS uploads (
                id TEXT PRIMARY KEY, profile TEXT NOT NULL, video TEXT NOT NULL,
                sha256 TEXT NOT NULL, title TEXT NOT NULL, is_aigc INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued', request_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
                lease_until REAL NOT NULL DEFAULT 0, created REAL NOT NULL,
                sent_at REAL, error TEXT, post_url TEXT,
                UNIQUE(profile, sha256)
            );
        """)

    def scan(self, config):
        added = 0
        for directory in config["watch_directories"]:
            for manifest in sorted(directory.glob("*.post.json")):
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                    profile = data["profile"]
                    if profile not in config["profiles"]:
                        raise ValueError("Unknown profile")
                    video = (directory / data["video"]).resolve()
                    if video.parent != directory or video.suffix.lower() not in {".mp4", ".mov", ".webm"}:
                        raise ValueError("Video must be in the watched directory")
                    if not video.is_file() or not video.stat().st_size:
                        raise ValueError("Video is missing or empty")
                    title = data["title"]
                    if not isinstance(title, str) or len(title) > 2200:
                        raise ValueError("Title must be a string of at most 2200 characters")
                    if not isinstance(data.get("is_aigc", False), bool):
                        raise ValueError("is_aigc must be a boolean")
                    with self.db:
                        cursor = self.db.execute("""INSERT OR IGNORE INTO uploads
                            (id, profile, video, sha256, title, is_aigc, created)
                            VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (str(uuid.uuid4()), profile, str(video), digest(video), title,
                             int(data.get("is_aigc", False)), time.time()))
                        added += cursor.rowcount
                except (ValueError, KeyError, OSError, TypeError) as error:
                    print(f"Skipped {manifest.name}: {error}")
        return added

    def rows(self):
        return [dict(row) for row in self.db.execute("SELECT * FROM uploads ORDER BY created")]

    def update(self, job_id, **fields):
        fields["lease_until"] = 0
        with self.db:
            self.db.execute("UPDATE uploads SET " + ", ".join(f"{k}=?" for k in fields) + " WHERE id=?",
                            (*fields.values(), job_id))

    def claim(self, config, now):
        # A lease coordinates workers. Expired in-flight uploads are polled before any resend.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            for row in self.db.execute("""SELECT * FROM uploads WHERE
                    status IN ('queued', 'retry', 'uploading', 'processing', 'checking')
                    AND next_at <= ? AND lease_until <= ? ORDER BY created""", (now, now)).fetchall():
                profile = config["profiles"].get(row["profile"])
                if not profile:
                    continue
                if row["status"] in {"queued", "retry"}:
                    last = self.db.execute("SELECT MAX(sent_at) FROM uploads WHERE profile=?",
                                           (row["profile"],)).fetchone()[0]
                    if last is not None and now - last < float(profile.get("min_interval_seconds", 3600)):
                        continue
                    state = "uploading"
                else:
                    state = "checking" if row["status"] == "uploading" else row["status"]
                self.db.execute("UPDATE uploads SET status=?, lease_until=? WHERE id=?",
                                (state, now + 900, row["id"]))
                self.db.commit()
                job = dict(row)
                job["status"] = state
                return job
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return None


@contextmanager
def worker_lock(path):
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if lock_path.stat().st_size == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("Another upload worker is using this database")
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class ProviderError(Exception):
    def __init__(self, message, transient=False, uncertain=False):
        super().__init__(message)
        self.transient = transient
        self.uncertain = uncertain


class UploadPost:
    BASE = "https://api.upload-post.com/api"

    def __init__(self, key, session=None):
        if session is None:
            import requests
            session = requests.Session()
        self.session = session
        self.headers = {"Authorization": f"Apikey {key}"}

    def request(self, method, route, **kwargs):
        import requests
        try:
            response = self.session.request(method, self.BASE + route,
                                           timeout=(15, 600), allow_redirects=False, **kwargs)
        except requests.RequestException:
            # Never store exception strings which may include credentials or request bodies.
            raise ProviderError("Network failure", transient=True, uncertain=(method == "POST"))
        if response.status_code == 404 and method == "GET":
            return {"status": "not_found"}
        if not 200 <= response.status_code < 300:
            raise ProviderError(f"Provider HTTP {response.status_code}",
                                transient=response.status_code == 429 or response.status_code >= 500,
                                uncertain=method == "POST" and response.status_code >= 500)
        try:
            return response.json()
        except ValueError:
            raise ProviderError("Invalid provider response", uncertain=method == "POST")

    def submit(self, job, profile):
        headers = dict(self.headers, **{"Idempotency-Key": job["id"]})
        with Path(job["video"]).open("rb") as video:
            return self.request("POST", "/upload", headers=headers,
                                data={"user": profile["user"], "platform[]": "tiktok",
                                      "title": job["title"], "async_upload": "true",
                                      "request_id": job["id"], "external_id": job["id"],
                                      "privacy_level": profile["privacy_level"],
                                      "disable_inbox_fallback": "true", "post_mode": "DIRECT_POST",
                                      "is_aigc": str(bool(job["is_aigc"])).lower()},
                                files={"video": (Path(job["video"]).name, video, "application/octet-stream")})

    def status(self, request_id):
        return self.request("GET", "/uploadposts/status", headers=self.headers,
                            params={"request_id": request_id})


def outcome(data):
    """Never equate accepted, skipped or inbox-delivered uploads with a live post."""
    results = data.get("results", [])
    if isinstance(results, dict):
        results = [dict(value, platform=key) for key, value in results.items() if isinstance(value, dict)]
    tiktok = next((r for r in results if r.get("platform") == "tiktok"), None)
    if tiktok:
        if tiktok.get("fallback_to_inbox") or "Inbox" in str(tiktok.get("post_url", "")):
            return "needs_action", None
        if tiktok.get("skipped") or tiktok.get("status") == "skipped":
            return "failed", None
        if tiktok.get("status") == "failed" or tiktok.get("success") is False:
            return "failed", None
        if tiktok.get("status") == "completed" or (data.get("status") == "completed" and tiktok.get("success") is True):
            return "published", tiktok.get("post_url")
    if data.get("status") == "failed" or data.get("success") is False:
        return "failed", None
    if data.get("status") == "completed":
        return "needs_action", None  # Completed without an explicit TikTok success result.
    return "processing", None


def work_once(queue, config, provider, now=None):
    now = time.time() if now is None else now
    job = queue.claim(config, now)
    if job is None:
        return False
    try:
        if job["status"] == "uploading":
            if digest(Path(job["video"])) != job["sha256"]:
                raise ValueError("Queued video changed; use a new manifest")
            queue.db.execute("UPDATE uploads SET attempts=attempts+1, sent_at=? WHERE id=?", (now, job["id"]))
            queue.db.commit()
            data = provider.submit(job, config["profiles"][job["profile"]])
            request_id = data.get("request_id") or job["id"]
        else:
            request_id = job["request_id"] or job["id"]
            data = provider.status(request_id)
            if data.get("status") == "not_found":
                # Unknown after a possibly accepted POST must be reconciled manually.
                queue.update(job["id"], status="needs_action", error="Request not found; check provider history before retrying")
                return True
        status, url = outcome(data)
        queue.update(job["id"], status=status, request_id=request_id, post_url=url,
                     next_at=now + 15, error=None if status in {"processing", "published"} else "Check provider history for TikTok result")
    except ProviderError as error:
        if error.uncertain or job["status"] != "uploading":
            status = "checking" if error.transient or error.uncertain else "needs_action"
        else:
            status = "retry" if error.transient and job["attempts"] < 4 else "failed"
        queue.update(job["id"], status=status, next_at=now + min(3600, 60 * 2 ** min(job["attempts"], 6)),
                     error=str(error))
    except (OSError, ValueError, TypeError, AttributeError) as error:
        queue.update(job["id"], status="needs_action", error=f"Local error: {type(error).__name__}")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("command", choices=["scan", "status", "run"])
    parser.add_argument("--publish", action="store_true", help="Enable actual uploads; otherwise only scan")
    parser.add_argument("--once", action="store_true", help="Run a single scan/worker cycle")
    args = parser.parse_args()
    try:
        config = load_config(args.config.resolve())
        queue = Queue(config["database"])
        provider = None
        if args.command == "run" and args.publish:
            key = os.environ.get("UPLOAD_POST_API_KEY", "")
            if not key:
                raise ValueError("Set UPLOAD_POST_API_KEY in the environment")
            provider = UploadPost(key)
        if args.command == "status":
            print(json.dumps(queue.rows(), indent=2))
            return
        with worker_lock(config["database"]):
            while True:
                print(f"Queued {queue.scan(config)} new video(s)", flush=True)
                if provider:
                    work_once(queue, config, provider)
                if args.command == "scan" or args.once:
                    break
                time.sleep(float(config.get("poll_seconds", 15)))
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"Uploader: {error}\n")
    except KeyboardInterrupt:
        print("Uploader stopped; queue saved.")


if __name__ == "__main__":
    main()
