"""Seeded countryball physics and the shared preview/export renderer."""
import math
import json
import random
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps
from pydantic import BaseModel, Field, model_validator

ASSETS = Path(__file__).resolve().parent / 'assets'
COUNTRIES = json.loads((ASSETS / 'countries.json').read_text(encoding='utf-8'))
SCALE = 2
WIDTH, HEIGHT = 1080, 1920
BOX = (58, 268, 482, 692)
RADIUS = 38
ORBIT, BLADE = 58, 44
FPS = 60
PHYSICS_HZ = 120
STEP = 1 / PHYSICS_HZ
FINALE_SECONDS = 1.6
SHAKE_SECONDS = .24
MOVE_ACCELERATION = 0.025  # Add 2.5% of starting speed each second.
SPIN_ACCELERATION = 0.04  # Add 4% of starting rotation speed each second.
ENGAGEMENT_DELAY = 2.0
POWER_COLORS = {'shield': '#6edaff', 'rage': '#ff6489', 'twin': '#c89aff',
                'heal': '#6dffc3', 'overdrive': '#ffda72'}


class Settings(BaseModel):
    countries: list[str] = Field(default_factory=lambda: ['FR', 'JP'], min_length=2, max_length=2)
    hp: int = Field(100, ge=10, le=500)
    damage: int = Field(12, ge=1, le=100)
    speed: int = Field(170, ge=60, le=350)
    rotation: float = Field(3.5, ge=0.5, le=10)
    duration: int = Field(30, ge=3, le=120)
    seed: int = Field(42, ge=0, le=2147483647)

    @model_validator(mode='after')
    def validate_countries(self):
        if len(set(self.countries)) != len(self.countries) or any(c not in COUNTRIES for c in self.countries):
            raise ValueError('Select exactly two distinct supported countries')
        return self


@dataclass
class Ball:
    country: str
    x: float
    y: float
    vx: float
    vy: float
    angle: float
    hp: int
    flash: float = 0
    rotation_direction: int = 1
    shield: int = 0
    shield_until: float = 0
    rage_until: float = 0
    twin_until: float = 0
    speed_multiplier: float = 1
    spin_multiplier: float = 1


@dataclass
class PowerUp:
    kind: str
    x: float
    y: float
    expires: float


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    color: str


@dataclass
class Ring:
    x: float
    y: float
    color: str
    age: float = 0
    duration: float = 0.5


def segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


class Battle:
    def __init__(self, settings):
        self.settings = settings
        rng = random.Random(settings.seed)
        self.rng = rng
        self.fx_rng = random.Random(settings.seed ^ 0xF1A5)
        self.time = 0.0
        self.balls = []
        self.cooldowns = {}
        self.hits = []
        self.last_hit = 'Every country for itself.'
        self.powerups = []
        self.particles = []
        self.rings = []
        self.next_spawn = 2.0
        self.power_cycle = list(POWER_COLORS)
        rng.shuffle(self.power_cycle)
        self.spawn_count = 0
        self.playback_time = None
        self.hitstop_remaining = 0
        self.shake_until = 0
        self.shake_strength = 0
        self.resolved_at = None
        self.sound_events = []
        self.next_whoosh = 0
        self.next_beat = 0.8
        self.comeback_spawned = set()
        self.peak_urgency = 0
        for i, country in enumerate(settings.countries):
            x = 210 + i * 120
            y = 455 + i * 50
            facing = math.atan2(50, 120) + (0 if i == 0 else math.pi)
            angle = facing + rng.uniform(-0.12, 0.12)
            self.balls.append(Ball(country, x, y, math.cos(angle) * settings.speed,
                                   math.sin(angle) * settings.speed, facing + rng.uniform(-0.15, 0.15), settings.hp))

    @property
    def screen_time(self):
        return self.time if self.playback_time is None else self.playback_time

    @property
    def urgency(self):
        if len(self.alive) < 2:
            return 0
        return 1 - min(ball.hp for ball in self.alive) / self.settings.hp

    def sound(self, kind, gain=1):
        self.sound_events.append({'kind': kind, 'time': self.screen_time, 'gain': gain})

    @property
    def finished(self):
        return self.resolved_at is not None and self.screen_time - self.resolved_at >= FINALE_SECONDS

    def advance_frame(self):
        if self.playback_time is None:
            self.playback_time = 0.0
        for _ in range(PHYSICS_HZ // FPS):
            self.playback_time += STEP
            if self.hitstop_remaining > 0:
                self.hitstop_remaining = max(0, self.hitstop_remaining - STEP)
            else:
                self.step()

    @property
    def alive(self):
        return [b for b in self.balls if b.hp > 0]

    @staticmethod
    def dagger(ball, offset=0):
        c, s = math.cos(ball.angle + offset), math.sin(ball.angle + offset)
        return (ball.x + ORBIT * c, ball.y + ORBIT * s,
                ball.x + (ORBIT + BLADE) * c, ball.y + (ORBIT + BLADE) * s)

    def daggers(self, ball):
        return [self.dagger(ball)] + ([self.dagger(ball, math.pi)] if ball.twin_until > self.time else [])

    def burst(self, x, y, color, count=18):
        self.rings.append(Ring(x, y, color))
        for _ in range(count):
            angle = self.fx_rng.uniform(0, math.tau)
            speed = self.fx_rng.uniform(45, 220)
            self.particles.append(Particle(x, y, math.cos(angle) * speed, math.sin(angle) * speed,
                                           self.fx_rng.uniform(0.2, 0.65), color))
        self.particles = self.particles[-160:]

    def tremble(self, strength):
        remaining = max(0, self.shake_until - self.screen_time)
        current = self.shake_strength * min(1, remaining / SHAKE_SECONDS)
        self.shake_strength = max(strength, current)
        self.shake_until = self.screen_time + SHAKE_SECONDS

    def apply_powerup(self, ball, kind):
        if kind == 'shield':
            ball.shield, ball.shield_until = 2, self.time + 8
        elif kind == 'rage':
            ball.rage_until = self.time + 6
        elif kind == 'twin':
            ball.twin_until = self.time + 6
        elif kind == 'heal':
            ball.hp = min(self.settings.hp, ball.hp + max(1, self.settings.hp // 4))
        elif kind == 'overdrive':
            ball.speed_multiplier = min(3, ball.speed_multiplier * 1.2)
            ball.spin_multiplier = min(3, ball.spin_multiplier * 1.25)
        self.burst(ball.x, ball.y, POWER_COLORS[kind], 28)
        self.sound(kind, .8)

    def spawn_powerup(self):
        # Both contenders compete for the same small, central pickup area.
        center_x, center_y = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
        for _ in range(12):
            angle = self.rng.uniform(0, math.tau)
            radius = math.sqrt(self.rng.random()) * 42
            x, y = center_x + math.cos(angle) * radius, center_y + math.sin(angle) * radius
            if all(math.hypot(x - p.x, y - p.y) >= 34 for p in self.powerups):
                break
        kind = self.power_cycle[self.spawn_count % len(self.power_cycle)]
        self.spawn_count += 1
        self.powerups.append(PowerUp(kind, x, y, self.time + 10))
        self.rings.append(Ring(x, y, POWER_COLORS[kind]))

    def steer_contenders(self, active, dt):
        quiet_time = self.time - (self.hits[-1] if self.hits else 0)
        if len(active) != 2 or quiet_time <= ENGAGEMENT_DELAY:
            return
        first, second = active
        dx, dy = second.x - first.x, second.y - first.y
        if math.hypot(dx, dy) <= RADIUS * 2 + 8:
            return
        # Snapshot both headings before applying any turn, preserving symmetry.
        target_angle = math.atan2(dy, dx)
        ramp = min(1, (quiet_time - ENGAGEMENT_DELAY) / 1.5)
        for ball, desired in ((first, target_angle), (second, target_angle + math.pi)):
            speed = math.hypot(ball.vx, ball.vy)
            heading = math.atan2(ball.vy, ball.vx)
            difference = math.atan2(math.sin(desired - heading), math.cos(desired - heading))
            max_turn = 1.4 * ramp * max(1, speed / self.settings.speed) * dt
            heading += max(-max_turn, min(max_turn, difference))
            ball.vx, ball.vy = math.cos(heading) * speed, math.sin(heading) * speed

    @property
    def movement_speed(self):
        return self.settings.speed * (1 + MOVE_ACCELERATION * self.time) * (1 + .3 * max(self.peak_urgency, self.urgency))

    @property
    def rotation_speed(self):
        return self.settings.rotation * (1 + SPIN_ACCELERATION * self.time) * (1 + .4 * max(self.peak_urgency, self.urgency))

    @staticmethod
    def set_speed(ball, speed):
        magnitude = math.hypot(ball.vx, ball.vy)
        if magnitude < 1e-9:
            ball.vx, ball.vy = math.cos(ball.angle) * speed, math.sin(ball.angle) * speed
        else:
            ball.vx *= speed / magnitude
            ball.vy *= speed / magnitude

    def step(self, dt=STEP):
        # Keep fast daggers and balls from skipping over contact at high speeds.
        future_time = self.time + dt
        movement = max((max(math.hypot(b.vx, b.vy), self.settings.speed *
                       (1 + MOVE_ACCELERATION * future_time) * 1.3 * b.speed_multiplier) for b in self.alive), default=0)
        rotation = self.settings.rotation * (1 + SPIN_ACCELERATION * future_time) * 1.4 * max((b.spin_multiplier for b in self.alive), default=1)
        subdivisions = max(1, math.ceil((2 * movement + (ORBIT + BLADE) * rotation) * dt / 8))
        for _ in range(subdivisions):
            self._step(dt / subdivisions)

    def _step(self, dt):
        self.time += dt
        self.peak_urgency = max(self.peak_urgency, self.urgency)
        for p in self.particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.life -= dt
        self.particles = [p for p in self.particles if p.life > 0]
        for ring in self.rings:
            ring.age += dt
        self.rings = [r for r in self.rings if r.age < r.duration]
        active = self.alive
        if not active:
            return
        self.steer_contenders(active, dt)
        if len(active) == 2:
            if self.time >= self.next_whoosh:
                self.sound('whoosh', .3 + self.urgency * .35)
                self.next_whoosh = self.time + max(.18, .65 / (1 + self.rotation_speed / 6))
            if self.time >= self.next_beat:
                self.sound('heartbeat', .15 + self.urgency * .5)
                self.next_beat = self.time + 1.1 - .65 * self.urgency
        speeds = {}
        for ball in active:
            # Collision response may change direction, but never reduce speed.
            speeds[ball.country] = max(self.movement_speed * ball.speed_multiplier, math.hypot(ball.vx, ball.vy))
            self.set_speed(ball, speeds[ball.country])
            ball.flash = max(0, ball.flash - dt)
            ball.angle = (ball.angle + ball.rotation_direction * self.rotation_speed * ball.spin_multiplier * dt) % math.tau
            if ball.shield_until <= self.time:
                ball.shield = 0
            ball.x += ball.vx * dt
            ball.y += ball.vy * dt
            left, top, right, bottom = BOX
            if ball.x < left + RADIUS or ball.x > right - RADIUS:
                ball.x = max(left + RADIUS, min(right - RADIUS, ball.x))
                ball.vx *= -1
                self.tremble(5)
                self.burst(ball.x, ball.y, '#5485b0', 5)
            if ball.y < top + RADIUS or ball.y > bottom - RADIUS:
                ball.y = max(top + RADIUS, min(bottom - RADIUS, ball.y))
                ball.vy *= -1
                self.tremble(5)
                self.burst(ball.x, ball.y, '#5485b0', 5)
        self.powerups = [p for p in self.powerups if p.expires > self.time]
        # Offer one genuine comeback opportunity per contender, contested at center.
        for ball in active:
            if len(active) == 2 and ball.hp <= self.settings.hp * .25 and ball.country not in self.comeback_spawned:
                self.comeback_spawned.add(ball.country)
                if len(self.powerups) >= 2:
                    self.powerups.pop(0)
                cx, cy = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
                self.powerups.append(PowerUp('heal', cx, cy, self.time + 8))
                self.rings.append(Ring(cx, cy, POWER_COLORS['heal']))
        if len(active) == 2 and self.time >= self.next_spawn:
            if len(self.powerups) < 2:
                self.spawn_powerup()
            self.next_spawn = self.time + 5
        for power in self.powerups[:]:
            for ball in active:
                if math.hypot(power.x - ball.x, power.y - ball.y) < RADIUS + 17:
                    self.apply_powerup(ball, power.kind)
                    self.powerups.remove(power)
                    speeds[ball.country] = max(speeds[ball.country], self.movement_speed * ball.speed_multiplier)
                    break
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                dx, dy = b.x - a.x, b.y - a.y
                distance = math.hypot(dx, dy)
                if distance < RADIUS * 2:
                    nx, ny = (dx / distance, dy / distance) if distance > 0 else (1, 0)
                    overlap = (RADIUS * 2 - distance) / 2
                    a.x -= nx * overlap
                    a.y -= ny * overlap
                    b.x += nx * overlap
                    b.y += ny * overlap
                    relative = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny
                    if relative > 0:
                        self.tremble(9)
                        self.burst((a.x + b.x) / 2, (a.y + b.y) / 2, '#b9d9f1', 8)
                        a.vx -= relative * nx
                        a.vy -= relative * ny
                        b.vx += relative * nx
                        b.vy += relative * ny
        # Resolve hits simultaneously, so country order does not decide trades.
        pending = []
        for attacker in active:
            for target in active:
                key = (attacker.country, target.country)
                if attacker is target or self.cooldowns.get(key, 0) > self.time:
                    continue
                if any(segment_distance(target.x, target.y, *blade) <= RADIUS + 3 for blade in self.daggers(attacker)):
                    pending.append((attacker, target))
                    self.cooldowns[key] = self.time + 0.45
        for attacker, target in pending:
            damage = self.settings.damage * (2 if attacker.rage_until > self.time else 1)
            if target.shield > 0:
                target.shield -= 1
                self.burst(target.x, target.y, POWER_COLORS['shield'])
                self.sound('shield' if target.shield else 'shatter', .9)
            else:
                was_alive = target.hp > 0
                target.hp = max(0, target.hp - damage)
                self.burst(target.x, target.y, '#ff6489')
                self.sound('hit', .7 + self.urgency * .4)
                if was_alive and target.hp == 0:
                    self.burst(target.x, target.y, '#ffda72', 50)
                    self.sound('knockout')
            self.hitstop_remaining = max(self.hitstop_remaining, .09 if target.hp == 0 else .05 if damage >= self.settings.damage * 2 else .025)
            self.tremble(14 if target.hp == 0 else 9 if damage >= self.settings.damage * 2 else 6)
            target.flash = 0.16
            self.hits.append(self.time)
            self.last_hit = f'{attacker.country} hits {target.country}  -{self.settings.damage} HP'
        self.peak_urgency = max(self.peak_urgency, self.urgency)
        if self.resolved_at is None and len(self.alive) < 2:
            self.resolved_at = self.screen_time
            self.powerups.clear()
            self.sound('victory' if self.alive else 'draw', .9)
            cx, cy = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
            self.burst(cx, cy, '#ffda72', 60)
        # Reverse once per impacting dagger, even if it contacts multiple balls.
        for country in {attacker.country for attacker, _ in pending}:
            next(ball for ball in active if ball.country == country).rotation_direction *= -1
        # Clamp again after body separation so balls always remain inside the box.
        for ball in active:
            self.set_speed(ball, speeds[ball.country])
            ball.x = max(BOX[0] + RADIUS, min(BOX[2] - RADIUS, ball.x))
            ball.y = max(BOX[1] + RADIUS, min(BOX[3] - RADIUS, ball.y))


class SharpDraw:
    """Draw physics coordinates directly at full HD resolution."""
    def __init__(self, image):
        self.draw = ImageDraw.Draw(image)

    def __getattr__(self, method):
        def scaled(coords, **kwargs):
            def scale(value):
                if isinstance(value, (tuple, list)):
                    return tuple(scale(part) for part in value)
                return round(value * SCALE)
            for key in ('width', 'radius'):
                if key in kwargs:
                    kwargs[key] = round(kwargs[key] * SCALE)
            return getattr(self.draw, method)(scale(coords), **kwargs)
        return scaled


class Renderer:
    def __init__(self):
        self.flags = {}
        self.background = Image.new('RGB', (WIDTH, HEIGHT), '#080d18')
        d = SharpDraw(self.background)
        d.rounded_rectangle(BOX, radius=12, fill='#101b2c', outline='#8da7c4', width=2)
        left, top, right, bottom = BOX
        d.rounded_rectangle((left + 4, top + 4, right - 4, bottom - 4), radius=10, outline='#263d56', width=1)

    def flag(self, code):
        size = RADIUS * 2
        with Image.open(ASSETS / 'flags' / f'{code}.png') as source:
            # Preserve emblem proportions when fitting the flag into a ball.
            im = ImageOps.fit(source.convert('RGBA'), (size * SCALE, size * SCALE), Image.Resampling.LANCZOS)
        mask = Image.new('L', (size * SCALE, size * SCALE))
        SharpDraw(mask).ellipse((0, 0, size - 0.5, size - 0.5), fill=255)
        im.putalpha(mask)
        return im

    def render(self, battle):
        im = self.background.copy()
        d = SharpDraw(im)
        if battle.urgency > .5:
            color = '#ff6489' if math.sin(battle.screen_time * math.tau) > 0 else '#874055'
            d.rounded_rectangle(BOX, radius=12, outline=color, width=2)
        for power in battle.powerups:
            color = POWER_COLORS[power.kind]
            x, y = power.x, power.y
            radius = 21 + 3 * math.sin(battle.time * 5)
            d.ellipse((x - radius, y - radius, x + radius, y + radius), outline=color, width=1)
            d.polygon([(x, y - 16), (x + 16, y), (x, y + 16), (x - 16, y)], fill='#162a40', outline=color, width=2)
            if power.kind == 'heal':
                d.line((x - 7, y, x + 7, y), fill=color, width=4)
                d.line((x, y - 7, x, y + 7), fill=color, width=4)
            elif power.kind == 'shield':
                d.polygon([(x - 7, y - 7), (x + 7, y - 7), (x + 6, y + 3), (x, y + 9), (x - 6, y + 3)], outline=color, width=2)
            elif power.kind == 'overdrive':
                d.polygon([(x + 3, y - 10), (x - 6, y + 1), (x, y + 1), (x - 3, y + 10), (x + 7, y - 2), (x + 1, y - 2)], fill=color)
            else:
                for offset in ((-4, 4) if power.kind == 'twin' else (0,)):
                    d.line((x + offset - 3, y + 8, x + offset + 3, y - 8), fill=color, width=3)
        for ball in battle.alive:
            x, y = ball.x, ball.y
            aura = (POWER_COLORS['shield'] if ball.shield else POWER_COLORS['rage'] if ball.rage_until > battle.time
                    else POWER_COLORS['twin'] if ball.twin_until > battle.time else POWER_COLORS['overdrive'] if ball.speed_multiplier > 1 else '#3c6588')
            for i in range(4, 0, -1):
                magnitude = math.hypot(ball.vx, ball.vy) or 1
                tx, ty = x - ball.vx / magnitude * i * 10, y - ball.vy / magnitude * i * 10
                radius = RADIUS - i * 4
                d.ellipse((tx - radius, ty - radius, tx + radius, ty + radius), outline='#25415b', width=2)
            d.ellipse((x - RADIUS - 6, y - RADIUS - 6, x + RADIUS + 6, y + RADIUS + 6), outline=aura, width=2)
            if ball.hp <= battle.settings.hp * .25:
                pulse = 9 + 3 * math.sin(battle.screen_time * math.tau * 1.5)
                d.ellipse((x - RADIUS - pulse, y - RADIUS - pulse, x + RADIUS + pulse, y + RADIUS + pulse), outline='#ff6489', width=2)
            d.ellipse((x - RADIUS - 2, y - RADIUS + 5, x + RADIUS + 2, y + RADIUS + 9), fill='#060c16')
            # A short arc makes the changing spin direction visible without labels.
            for i in range(6, 0, -1):
                angle = ball.angle - ball.rotation_direction * i * 0.085
                tx, ty = x + (ORBIT + 8) * math.cos(angle), y + (ORBIT + 8) * math.sin(angle)
                d.ellipse((tx - 1.5, ty - 1.5, tx + 1.5, ty + 1.5), fill='#344b61')
            for ax, ay, bx, by in battle.daggers(ball):
                c, s = (bx - ax) / BLADE, (by - ay) / BLADE
                d.line((ax - c * 12, ay - s * 12, ax, ay), fill='#060b14', width=7)
                d.line((ax - c * 11, ay - s * 11, ax, ay), fill='#ad7536', width=4)
                d.line((ax - s * 8, ay + c * 8, ax + s * 8, ay - c * 8), fill='#ffe2a2', width=3)
                d.polygon([(ax - s * 5, ay + c * 5), (bx, by), (ax + s * 5, ay - c * 5)], fill=POWER_COLORS['rage'] if ball.rage_until > battle.time else '#f2fcff', outline='#94b4c8', width=1)
                d.polygon([(ax, ay), (bx, by), (ax + s * 5, ay - c * 5)], fill='#8faabd')
            if ball.country not in self.flags:
                self.flags[ball.country] = self.flag(ball.country)
            im.paste(self.flags[ball.country], (round((x - RADIUS) * SCALE), round((y - RADIUS) * SCALE)), self.flags[ball.country])
            d.ellipse((x - RADIUS, y - RADIUS, x + RADIUS, y + RADIUS), outline='#ff677d' if ball.flash else '#f5faff', width=1.5)
            if ball.flash:
                d.ellipse((x - RADIUS - 4, y - RADIUS - 4, x + RADIUS + 4, y + RADIUS + 4), outline='#ff677d', width=1)
            d.rounded_rectangle((x - 26, y + RADIUS + 8, x + 26, y + RADIUS + 13), radius=2, fill='#26344b')
            fill_width = max(2, 52 * ball.hp / battle.settings.hp)
            d.rounded_rectangle((x - 26, y + RADIUS + 8, x - 26 + fill_width, y + RADIUS + 13), radius=2, fill='#ff677d' if ball.flash or ball.hp <= battle.settings.hp * .25 else '#67e8ce')
            if len(battle.alive) == 1:
                d.polygon([(x - 14, y - RADIUS - 11), (x - 18, y - RADIUS - 24), (x - 7, y - RADIUS - 19),
                           (x, y - RADIUS - 30), (x + 7, y - RADIUS - 19), (x + 18, y - RADIUS - 24), (x + 14, y - RADIUS - 11)], fill='#ffda79')
        if battle.resolved_at is not None and battle.screen_time - battle.resolved_at > .25:
            im = Image.blend(im, Image.new('RGB', im.size, '#080d18'), .75)
            d = SharpDraw(im)
            cx, cy = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
            if battle.alive:
                for radius in (98, 112, 125):
                    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline='#ba9651', width=2)
                winner = battle.alive[0]
                flag = self.flags[winner.country].resize((160 * SCALE, 160 * SCALE), Image.Resampling.LANCZOS)
                im.paste(flag, (round((cx - 80) * SCALE), round((cy - 80) * SCALE)), flag)
                d.polygon([(cx - 24, cy - 98), (cx - 30, cy - 125), (cx - 12, cy - 115), (cx, cy - 140),
                           (cx + 12, cy - 115), (cx + 30, cy - 125), (cx + 24, cy - 98)], fill='#ffda72')
            else:
                for i, ball in enumerate(battle.balls):
                    flag = self.flags.get(ball.country) or self.flag(ball.country)
                    im.paste(flag, (round((cx - 85 + i * 95) * SCALE), round((cy - RADIUS) * SCALE)), flag)
        for ring in battle.rings:
            radius = 10 + ring.age * 120
            d.ellipse((ring.x - radius, ring.y - radius, ring.x + radius, ring.y + radius), outline=ring.color, width=max(1, 3 * (1 - ring.age / ring.duration)))
        for p in battle.particles:
            d.line((p.x - p.vx * 0.025, p.y - p.vy * 0.025, p.x, p.y), fill=p.color, width=2)
        if battle.shake_until > battle.screen_time:
            strength = battle.shake_strength * (battle.shake_until - battle.screen_time) / SHAKE_SECONDS
            offset_x = round(math.sin(battle.screen_time * 117) * strength * SCALE)
            offset_y = round(math.cos(battle.screen_time * 93) * strength * SCALE)
            shifted = Image.new('RGB', im.size, '#080d18')
            shifted.paste(im, (offset_x, offset_y))
            im = shifted
        return im


def ffmpeg_path():
    path = shutil.which('ffmpeg')
    if not path:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        path = shutil.which('ffmpeg')
    if not path:
        raise RuntimeError('Install FFmpeg or static-ffmpeg to export MP4')
    return path


def export_video(settings, destination, progress=lambda value: None):
    from audio import mix_audio
    import tempfile
    destination = Path(destination)
    with tempfile.TemporaryDirectory(dir=destination.parent) as staging:
        staging = Path(staging)
        battle, frame_count = render_video(settings, staging / 'silent.mp4', lambda value: progress(round(value * .9)))
        mix_audio(battle.sound_events, frame_count / FPS, staging / 'audio.wav')
        try:
            subprocess.run([ffmpeg_path(), '-y', '-v', 'error', '-i', str(staging / 'silent.mp4'),
                            '-i', str(staging / 'audio.wav'), '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
                            '-shortest', '-movflags', '+faststart', str(destination)],
                           capture_output=True, check=True, timeout=120)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    progress(100)


def render_video(settings, destination, progress=lambda value: None):
    battle, renderer = Battle(settings), Renderer()
    fps = FPS
    frames = settings.duration * fps
    command = [ffmpeg_path(), '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{WIDTH}x{HEIGHT}', '-r', str(fps), '-i', '-', '-an', '-c:v', 'libx264',
               '-preset', 'veryfast', '-crf', '17', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(destination)]
    # A file avoids pipe deadlocks if FFmpeg emits a long error message.
    import tempfile
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        try:
            frame_count = 0
            for frame in range(frames + math.ceil(FINALE_SECONDS * fps)):
                if battle.finished or (frame >= frames and battle.resolved_at is None):
                    break
                process.stdin.write(renderer.render(battle).tobytes())
                frame_count += 1
                battle.advance_frame()
                if frame % fps == 0:
                    progress(min(99, round(frame / frames * 100)))
            process.stdin.close()
            if process.wait(timeout=60):
                raise RuntimeError('FFmpeg export failed')
        except BaseException:
            process.kill()
            process.wait()
            Path(destination).unlink(missing_ok=True)
            errors.seek(0)
            details = errors.read().decode(errors='replace')[-2000:]
            if details:
                raise RuntimeError(details) from None
            raise
    progress(100)
    return battle, frame_count
