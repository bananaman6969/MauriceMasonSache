import math
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine import ASSETS, COUNTRIES, Battle, BOX, RADIUS, Renderer, Settings, STEP, PowerUp
from app import app


def duel(hp=100, damage=12):
    battle = Battle(Settings(countries=['FR', 'JP'], hp=hp, damage=damage))
    a, b = battle.balls
    a.x, a.y, a.vx, a.vy, a.angle = 200, 400, 0, 0, 0
    b.x, b.y, b.vx, b.vy, b.angle = 300, 400, 0, 0, 0
    return battle, a, b


def test_dagger_damage_and_cooldown():
    battle, a, b = duel()
    battle.step()
    assert (a.hp, b.hp) == (100, 88)
    assert b.flash > 0
    for _ in range(20):
        a.angle = b.angle = 0
        a.x, a.y, b.x, b.y = 200, 400, 300, 400
        battle.step()
    assert b.hp == 88
    for _ in range(40):
        a.angle = b.angle = 0
        a.x, a.y, b.x, b.y = 200, 400, 300, 400
        battle.step()
    assert b.hp == 76


def test_last_survivor_keeps_moving_and_accelerating():
    battle, a, b = duel(hp=10, damage=20)
    battle.step()
    assert b.hp == 0
    assert battle.alive == [a]
    position = a.x, a.y
    speed = math.hypot(a.vx, a.vy)
    for _ in range(100):
        battle.step()
    assert (a.x, a.y) != position
    assert math.hypot(a.vx, a.vy) > speed
    assert a.hp == 10


def test_simultaneous_knockout():
    battle, a, b = duel(hp=10, damage=10)
    b.angle = math.pi
    battle.step()
    assert not battle.alive


def test_dagger_reverses_on_hit_and_keeps_direction_during_cooldown():
    battle, a, b = duel()
    battle.step()
    assert a.rotation_direction == -1
    assert b.rotation_direction == 1
    angle = a.angle
    battle.step()
    assert a.angle == pytest.approx((angle - battle.rotation_speed * STEP) % math.tau)
    assert a.rotation_direction == -1
    assert b.hp == 88


def test_walls_and_determinism():
    first, second = Battle(Settings()), Battle(Settings())
    for _ in range(3600):
        first.step()
        second.step()
        for ball in first.alive:
            assert BOX[0] + RADIUS <= ball.x <= BOX[2] - RADIUS
            assert BOX[1] + RADIUS <= ball.y <= BOX[3] - RADIUS
    assert first.balls == second.balls
    assert first.hits


def test_body_collision_bounces_without_damage():
    battle, a, b = duel()
    b.x = a.x + RADIUS * 2 - 1
    a.vx, b.vx = 100, -100
    a.angle, b.angle = math.pi, 0
    battle.step()
    assert a.vx < 0 < b.vx
    assert a.hp == b.hp == 100
    assert battle.shake_until > battle.screen_time
    assert battle.shake_strength >= 4


def test_glancing_collision_cannot_slow_either_ball():
    battle, a, b = duel()
    b.x = a.x + RADIUS * 2 - 1
    a.vx, a.vy = 160, 60
    b.vx, b.vy = -60, 160
    a.angle, b.angle = math.pi, 0
    before = [math.hypot(ball.vx, ball.vy) for ball in (a, b)]
    battle.step()
    for ball, previous in zip((a, b), before):
        assert math.hypot(ball.vx, ball.vy) >= previous - 1e-8


def test_movement_and_rotation_increase_throughout_battle():
    battle = Battle(Settings(hp=500, damage=1))
    previous = {ball.country: math.hypot(ball.vx, ball.vy) for ball in battle.balls}
    spin = battle.rotation_speed
    for _ in range(1200):
        battle.step()
        assert battle.rotation_speed > spin
        spin = battle.rotation_speed
        for ball in battle.alive:
            speed = math.hypot(ball.vx, ball.vy)
            assert speed >= previous[ball.country] - 1e-8
            previous[ball.country] = speed
    assert battle.movement_speed > battle.settings.speed
    assert battle.rotation_speed > battle.settings.rotation


@pytest.mark.parametrize('countries', [['FR'], ['FR', 'FR'], ['FR', 'XX'], ['FR', 'JP', 'BR']])
def test_invalid_countries(countries):
    with pytest.raises(ValidationError):
        Settings(countries=countries)


def test_api_validation_and_missing_files():
    client = TestClient(app)
    assert client.get('/').status_code == 200
    assert client.get('/api/countries').json()['JP'] == 'Japan'
    assert client.post('/api/export', json={'hp': -1}).status_code == 422
    assert client.get('/api/preview', params={'settings': '{} invalid'}).status_code == 422
    assert client.get('/api/download/not-a-job').status_code == 404
    assert client.get('/api/jobs/missing').status_code == 404


def test_render_winner_and_draw():
    battle, a, b = duel(hp=10, damage=10)
    renderer = Renderer()
    assert renderer.render(battle).size == (1080, 1920)
    b.hp = 0
    assert renderer.render(battle).mode == 'RGB'
    a.hp = 0
    assert renderer.render(battle).size == (1080, 1920)


def test_every_country_has_a_renderable_flag():
    assert len(COUNTRIES) >= 250
    renderer = Renderer()
    for code in COUNTRIES:
        assert (ASSETS / 'flags' / f'{code}.png').is_file()
        flag = renderer.flag(code)
        assert flag.size == (RADIUS * 4, RADIUS * 4)
        assert flag.getpixel((RADIUS * 2, RADIUS * 2))[3] > 0


def test_shield_blocks_hit_and_expires():
    battle, a, b = duel()
    battle.apply_powerup(b, 'shield')
    battle.step()
    assert b.hp == 100
    assert b.shield == 1
    assert a.rotation_direction == -1
    b.shield_until = battle.time
    battle.step()
    assert b.shield == 0


def test_rage_doubles_damage_and_expires():
    battle, a, b = duel()
    battle.apply_powerup(a, 'rage')
    battle.step()
    assert b.hp == 76
    a.rage_until = battle.time
    battle.cooldowns.clear()
    a.angle = b.angle = 0
    battle.step()
    assert b.hp == 64


def test_twin_blade_can_hit_from_opposite_side():
    battle, a, b = duel()
    a.angle = math.pi
    battle.apply_powerup(a, 'twin')
    assert len(battle.daggers(a)) == 2
    battle.step()
    assert b.hp == 88
    a.twin_until = battle.time
    assert len(battle.daggers(a)) == 1


def test_heal_capped_and_overdrive_never_slows_ball():
    battle, a, b = duel()
    a.hp = 90
    battle.apply_powerup(a, 'heal')
    assert a.hp == 100
    battle.step()
    speed = math.hypot(a.vx, a.vy)
    battle.apply_powerup(a, 'overdrive')
    battle.step()
    assert a.speed_multiplier == 1.2
    assert a.spin_multiplier == 1.25
    assert math.hypot(a.vx, a.vy) > speed


def test_pickup_consumed_by_contact_and_seeded_spawns():
    battle, a, b = duel()
    a.hp = 50
    battle.powerups.append(PowerUp('heal', a.x, a.y, 10))
    battle.step()
    assert a.hp == 75
    assert not battle.powerups
    first, second = Battle(Settings()), Battle(Settings())
    for _ in range(250):
        first.step()
        second.step()
    assert first.powerups == second.powerups
    assert first.particles == second.particles
    assert first.spawn_count == 1


def test_powerups_spawn_near_center():
    battle = Battle(Settings())
    center_x, center_y = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
    for _ in range(20):
        battle.powerups.clear()
        battle.spawn_powerup()
        power = battle.powerups[-1]
        assert math.hypot(power.x - center_x, power.y - center_y) <= 42 + 1e-8


def test_stalemate_steering_waits_then_turns_without_slowing():
    battle, a, b = duel()
    a.vx, a.vy, b.vx, b.vy = 0, -170, 0, 170
    battle.time = 1.9
    battle.steer_contenders(battle.alive, STEP)
    assert a.vx == b.vx == 0
    battle.time = 3.5
    battle.steer_contenders(battle.alive, STEP)
    assert a.vx > 0 > b.vx
    assert math.hypot(a.vx, a.vy) == pytest.approx(170)
    assert math.hypot(b.vx, b.vy) == pytest.approx(170)
    # A recent shield contact or damaging hit resets the quiet-time countdown.
    battle.hits.append(battle.time - 0.5)
    velocities = (a.vx, a.vy, b.vx, b.vy)
    battle.steer_contenders(battle.alive, STEP)
    assert (a.vx, a.vy, b.vx, b.vy) == velocities


def test_stalemate_steering_leaves_last_survivor_alone():
    battle, a, b = duel()
    battle.time = 10
    b.hp = 0
    a.vx, a.vy = 0, 170
    battle.steer_contenders(battle.alive, STEP)
    assert (a.vx, a.vy) == (0, 170)
