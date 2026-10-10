"""Original synthesized effects shared by live playback and MP4 audio."""
import io
import math
import random
import wave
from array import array
from functools import lru_cache

RATE = 24000
KINDS = ('whoosh', 'hit', 'shield', 'shatter', 'heal', 'rage', 'twin', 'overdrive', 'knockout', 'victory', 'draw', 'heartbeat')


@lru_cache(maxsize=32)
def samples(kind):
    if kind not in KINDS:
        raise ValueError('Unknown sound effect')
    duration = {'whoosh': .13, 'hit': .11, 'shield': .18, 'shatter': .28,
                'knockout': .5, 'victory': .85, 'draw': .5, 'heartbeat': .18}.get(kind, .32)
    rng = random.Random(KINDS.index(kind))
    output = array('f')
    phase = 0
    for i in range(int(duration * RATE)):
        t = i / RATE
        u = t / duration
        envelope = min(1, t * 300) * (1 - u) ** 2
        noise = rng.uniform(-1, 1)
        if kind == 'whoosh':
            value = noise * .22 * math.sin(math.pi * u) ** 2
        elif kind in ('hit', 'knockout', 'heartbeat'):
            frequency = (115 if kind == 'hit' else 70) * (1 - u * .6)
            phase += math.tau * frequency / RATE
            value = math.sin(phase) * .45 + noise * (.2 if kind != 'heartbeat' else .015)
        elif kind in ('shield', 'shatter'):
            phase += math.tau * (1700 - 900 * u) / RATE
            value = math.sin(phase) * .2 + noise * (.18 if kind == 'shield' else .38)
        else:
            notes = {'heal': (523, 659, 784), 'rage': (220, 330, 440), 'twin': (440, 554, 880),
                     'overdrive': (330, 660, 990), 'victory': (523, 659, 784, 1047), 'draw': (392, 330, 262)}[kind]
            frequency = notes[min(len(notes) - 1, int(u * len(notes)))]
            phase += math.tau * frequency / RATE
            value = math.sin(phase) * .3 + math.sin(phase * 2) * .08
        output.append(value * envelope)
    return output


def wav_bytes(values):
    pcm = array('h', (round(max(-.95, min(.95, value)) * 32767) for value in values))
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(pcm.tobytes())
    return buffer.getvalue()


def mix_audio(events, duration, destination):
    output = array('f', [0]) * math.ceil(duration * RATE)
    for event in events:
        start = max(0, round(event['time'] * RATE))
        effect = samples(event['kind'])
        for i in range(min(len(effect), len(output) - start)):
            output[start + i] += effect[i] * event['gain']
    destination.write_bytes(wav_bytes(output))
