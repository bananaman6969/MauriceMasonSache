from pathlib import Path

from fastapi.testclient import TestClient

import app as server
from core import gameplay


def test_cooking_presets_are_named_and_available():
    presets = [p for p in gameplay.GAMEPLAY_PRESETS if p['category'] == 'Cooking']
    assert len(presets) == 3
    assert len({p['id'] for p in presets}) == 3
    assert all(p['source'] == 'stock' and p['source_url'].startswith('https://mixkit.co/') for p in presets)


def test_background_library_classifies_cooking(tmp_path, monkeypatch):
    path = tmp_path / 'cooking_dough_mixing.mp4'
    path.write_bytes(b'video')
    monkeypatch.setattr(gameplay, 'get_gameplay_dir', lambda: str(tmp_path))
    monkeypatch.setattr(gameplay, 'probe_video_metadata', lambda path: {'duration': 8, 'filename': Path(path).name})
    video = gameplay.list_available_gameplay_videos()[0]
    assert video['category'] == 'Cooking'
    assert 'Dough Mixing' in video['display_name']


def test_cooking_download_routes_to_stock_loader(monkeypatch):
    preset = next(p for p in gameplay.GAMEPLAY_PRESETS if p['category'] == 'Cooking')
    monkeypatch.setattr(gameplay, 'download_stock_background', lambda selected: selected['id'] + '.mp4')
    assert gameplay.download_youtube_gameplay(preset['url']) == preset['id'] + '.mp4'


def test_valid_existing_stock_clip_is_reused(tmp_path, monkeypatch):
    preset = next(p for p in gameplay.GAMEPLAY_PRESETS if p['category'] == 'Cooking')
    path = tmp_path / (preset['id'] + '.mp4')
    path.write_bytes(b'video')
    monkeypatch.setattr(gameplay, 'get_gameplay_dir', lambda: str(tmp_path))
    monkeypatch.setattr(gameplay, 'probe_video_metadata', lambda path: {'duration': 13})
    assert gameplay.download_stock_background(preset) == str(path)


def test_download_success_and_failure_are_visible(monkeypatch):
    client = TestClient(server.app)
    monkeypatch.setattr(server, 'download_youtube_gameplay', lambda *args, **kwargs: '/library/cooking_dough_mixing.mp4')
    response = client.post('/api/gameplay/download', data={'url': 'https://example.test/video'})
    job = response.json()['download_id']
    assert client.get('/api/gameplay/download-status/' + job).json() == {
        'status': 'complete', 'filename': 'cooking_dough_mixing.mp4'}
    def fail(*args, **kwargs):
        raise RuntimeError('Download unavailable')
    monkeypatch.setattr(server, 'download_youtube_gameplay', fail)
    job = client.post('/api/gameplay/download', data={'url': 'https://example.test/video'}).json()['download_id']
    assert client.get('/api/gameplay/download-status/' + job).json()['status'] == 'failed'


def test_background_preview_supports_ranges_and_missing_files(tmp_path, monkeypatch):
    (tmp_path / 'clip.mp4').write_bytes(b'0123456789')
    monkeypatch.setattr(server, 'get_gameplay_dir', lambda: str(tmp_path))
    client = TestClient(server.app)
    response = client.get('/api/gameplay/preview/clip.mp4', headers={'Range': 'bytes=0-3'})
    assert response.status_code == 206
    assert response.content == b'0123'
    assert client.get('/api/gameplay/preview/missing.mp4').status_code == 404
    assert client.get('/api/gameplay/preview/private.txt').status_code == 404
    assert client.get('/api/gameplay/download-status/missing').status_code == 404
