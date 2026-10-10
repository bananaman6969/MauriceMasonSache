import io
import math
import sys
import wave
from array import array
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import Battle, FPS, Settings, STEP
from audio import KINDS, RATE, mix_audio, samples, wav_bytes
from app import app


def test_all_openings_clash_in_first_second():
    for seed in range(20):
        battle = Battle(Settings(seed=seed))
        for _ in range(120):
            battle.step()
            if battle.hits:
                break
        assert battle.hits and battle.hits[0] < 1


def test_hitstop_freezes_physics_but_advances_playback():
    battle = Battle(Settings())
    battle.advance_frame()
    battle.hitstop_remaining = .1
    time = battle.time
    playback = battle.playback_time
    position = [(b.x, b.y) for b in battle.balls]
    battle.advance_frame()
    assert battle.time == time
    assert battle.playback_time > playback
    assert [(b.x, b.y) for b in battle.balls] == position


def test_frame_advances_by_one_sixtieth_second():
    battle = Battle(Settings())
    battle.advance_frame()
    assert FPS == 60
    assert battle.playback_time == pytest.approx(1 / 60)
    for _ in range(59):
        battle.advance_frame()
    assert battle.playback_time == pytest.approx(1)


def test_healing_cannot_reduce_escalated_movement_or_spin():
    battle = Battle(Settings())
    ball = battle.balls[0]
    ball.hp = 20
    battle.step()
    speed, spin = math.hypot(ball.vx, ball.vy), battle.rotation_speed
    battle.apply_powerup(ball, 'heal')
    battle.step()
    assert math.hypot(ball.vx, ball.vy) >= speed - 1e-8
    assert battle.rotation_speed > spin


def test_comeback_heal_is_contested_and_spawned_once():
    battle = Battle(Settings())
    battle.balls[0].hp = 20
    battle.balls[0].x, battle.balls[0].y = 120, 340
    battle.balls[1].x, battle.balls[1].y = 420, 620
    battle.step()
    heals = [p for p in battle.powerups if p.kind == 'heal']
    assert len(heals) == 1
    assert (heals[0].x, heals[0].y) == (270, 480)
    battle.powerups.clear()
    battle.step()
    assert not battle.powerups


def test_finale_completes_after_short_celebration():
    battle = Battle(Settings(hp=10, damage=100))
    for _ in range(120):
        battle.advance_frame()
        if battle.finished:
            break
    assert battle.resolved_at is not None
    assert battle.finished
    assert 1.6 <= battle.screen_time - battle.resolved_at < 1.7
    assert any(e['kind'] in ('victory', 'draw') for e in battle.sound_events)
    assert any(e['kind'] == 'knockout' for e in battle.sound_events)


def test_all_effects_are_valid_non_silent_wav():
    for kind in KINDS:
        with wave.open(io.BytesIO(wav_bytes(samples(kind))), 'rb') as file:
            assert file.getframerate() == RATE
            assert file.getnchannels() == 1
            pcm = array('h', file.readframes(file.getnframes()))
            assert max(abs(value) for value in pcm) > 1000


def test_audio_mixer_aligns_event_with_presentation_time(tmp_path):
    path = tmp_path / 'mixed.wav'
    mix_audio([{'kind': 'hit', 'time': .5, 'gain': 1}], 1, path)
    with wave.open(str(path), 'rb') as file:
        pcm = array('h', file.readframes(file.getnframes()))
    assert len(pcm) == RATE
    assert all(value == 0 for value in pcm[:RATE // 2])
    assert any(value != 0 for value in pcm[RATE // 2:])


def test_audio_routes_and_invalid_events_settings():
    client = TestClient(app)
    assert client.get('/api/sounds/hit').content.startswith(b'RIFF')
    assert client.get('/api/sounds/not-real').status_code == 404
    assert client.get('/api/preview-events', params={'settings': 'invalid'}).status_code == 422
