"""Hollow Hull sound kit: every sound the game plays that the Paragon packs do not have.

The Paragon heroes come with their voices (grunts, pain, death), but no footsteps,
weapon sounds or music. These are synthesised here from noise and sine waves, so the
repo carries no licensed audio:

    music_ship     64 s seamless loop: hull drone, dissonant swells, groaning metal,
                   creaks and drips (the flooded ship)
    combat_layer   32 s seamless loop: slow war drums, low string ostinato and a high
                   trembling cluster; faded in over the music while monsters are close
    music_hollow   64 s seamless loop for The Hollow: a sub drone under a wordless choir
                   that slides between vowels, wet groans, whispers and drips in a huge
                   fleshy cave (the heartbeat is not in it: the heart itself plays it)
    step_<floor>_N footsteps on steel, wood, grate, in shallow water, and in The Hollow
                   on flesh (wet, sticky) and bone (a dry clatter)
    heartbeat      one lub-dub of the heart in The Hollow
    breath_N       something breathing behind the walls, with a wet rattle
    groan_N        a huge thing groaning somewhere in the dark
    sting_fall     the hold floor splitting and the fall into the water below
    sting_wake     waking in The Hollow: a low swell rising out of the silence
    hit_N          a blow landing on a body
    gunshot_N      Revenant's revolver
    whoosh_N       a monster's swing through the air

    python audio/make_audio.py        (needs numpy; writes audio/wav/*.wav)

The output is deterministic (fixed random seeds), so re-running only changes files
when this script changes. To give a new level its own music, add a music_<name>
function and a line in MUSIC, and name it in level/<level>.json as "music".
"""

import os
import wave

import numpy as np

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wav")
SR_SFX = 44100
SR_MUSIC = 32000


# --- building blocks ------------------------------------------------------

def spectral(x, sr, gain_fn):
    """Filter by multiplying the spectrum (circular, so loops stay seamless)."""
    spec = np.fft.rfft(x, axis=0)
    f = np.fft.rfftfreq(x.shape[0], 1.0 / sr)
    g = gain_fn(np.maximum(f, 1e-3))
    if spec.ndim == 2:
        g = g[:, None]
    return np.fft.irfft(spec * g, n=x.shape[0], axis=0)


def lowpass(x, sr, fc, order=2):
    return spectral(x, sr, lambda f: 1.0 / np.sqrt(1.0 + (f / fc) ** (2 * order)))


def highpass(x, sr, fc, order=2):
    return spectral(x, sr, lambda f: 1.0 / np.sqrt(1.0 + (fc / f) ** (2 * order)))


def bandpass(x, sr, lo, hi, order=2):
    return highpass(lowpass(x, sr, hi, order), sr, lo, order)


def resonance(x, sr, fc, q):
    """A single resonant peak (groaning metal, pipe ring)."""
    return spectral(x, sr, lambda f: 1.0 / np.sqrt(1.0 + (q * (f / fc - fc / f)) ** 2))


def env(n, attack, release, sr, curve=4.0):
    a = max(1, int(attack * sr))
    t = np.arange(n) / sr
    e = np.exp(-curve * np.maximum(t - attack, 0) / max(release, 1e-3))
    e[:a] *= np.linspace(0, 1, a)
    return e


def reverb_ir(sr, seconds, rng, stereo=False, damping=3000.0, predelay=0.02):
    n = int(seconds * sr)
    t = np.arange(n) / sr
    chans = []
    for _ in range(2 if stereo else 1):
        noise = rng.standard_normal(n) * np.exp(-6.9 * t / seconds)  # -60 dB at the end
        noise = lowpass(noise, sr, damping, 1)
        noise[: int(predelay * sr)] = 0
        chans.append(noise / np.sqrt(np.sum(noise ** 2)))
    return np.stack(chans, axis=1) if stereo else chans[0]


def circular_convolve(x, ir):
    """Reverb that wraps around the loop end, so the loop has no seam."""
    n = x.shape[0]
    pad = np.zeros((n,) + ir.shape[1:])
    pad[: min(n, ir.shape[0])] = ir[:n]
    if x.ndim == 2 and pad.ndim == 1:
        pad = np.stack([pad, pad], axis=1)
    if x.ndim == 1 and pad.ndim == 2:
        x = np.stack([x, x], axis=1)
    return np.fft.irfft(np.fft.rfft(x, axis=0) * np.fft.rfft(pad, axis=0), n=n, axis=0)


def tail_convolve(x, ir):
    """Reverb for a one-shot: the tail is kept after the dry sound."""
    n = x.shape[0] + ir.shape[0]
    return np.fft.irfft(np.fft.rfft(x, n) * np.fft.rfft(ir, n), n=n)


def place(buf, sound, at, wrap=True):
    """Add sound into buf at sample index at (wrapping round the loop end)."""
    n = buf.shape[0]
    idx = (np.arange(sound.shape[0]) + at)
    if wrap:
        idx %= n
    else:
        keep = idx < n
        idx, sound = idx[keep], sound[keep]
    np.add.at(buf, idx, sound)


def pan(mono, p):
    """Equal-power pan, p from -1 (left) to 1 (right)."""
    a = (p + 1) * np.pi / 4
    return np.stack([mono * np.cos(a), mono * np.sin(a)], axis=1)


def saw(freq, t, partials=12):
    out = np.zeros_like(t)
    for k in range(1, partials + 1):
        out += np.sin(2 * np.pi * freq * k * t) / k
    return out


def note(name):
    """'D2' -> Hz."""
    names = {"C": -9, "C#": -8, "Db": -8, "D": -7, "D#": -6, "Eb": -6, "E": -5, "F": -4, "F#": -3,
             "Gb": -3, "G": -2, "G#": -1, "Ab": -1, "A": 0, "A#": 1, "Bb": 1, "B": 2}
    pitch, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((names[pitch] + 12 * (octave - 4)) / 12)


def normalize(x, peak_db=-1.0):
    peak = np.max(np.abs(x))
    return x * (10 ** (peak_db / 20) / peak) if peak > 0 else x


def rms_to(x, target_db):
    rms = np.sqrt(np.mean(x ** 2))
    x = x * (10 ** (target_db / 20) / rms)
    peak = np.max(np.abs(x))
    return x * (0.97 / peak) if peak > 0.97 else x


def fade(x, sr, fade_in=0.002, fade_out=0.05):
    a, b = int(fade_in * sr), int(fade_out * sr)
    x = x.copy()
    if a:
        x[:a] *= np.linspace(0, 1, a)[:, None] if x.ndim == 2 else np.linspace(0, 1, a)
    if b:
        x[-b:] *= np.linspace(1, 0, b)[:, None] if x.ndim == 2 else np.linspace(1, 0, b)
    return x


def write(name, x, sr):
    os.makedirs(OUT, exist_ok=True)
    data = np.clip(x, -1, 1)
    chans = 1 if data.ndim == 1 else data.shape[1]
    pcm = (data * 32767).astype("<i2")
    with wave.open(os.path.join(OUT, name + ".wav"), "wb") as w:
        w.setnchannels(chans)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    print(f"{name}.wav  {x.shape[0] / sr:5.2f} s  {chans} ch")


# --- music ------------------------------------------------------------------

def music_ship():
    """The flooded ship: a cold low drone, slow dissonant swells, the hull groaning,
    creaks and drips, all in a big metal room. Loops seamlessly every 64 s."""
    sr, secs = SR_MUSIC, 64
    n = sr * secs
    t = np.arange(n) / sr
    rng = np.random.default_rng(11)
    out = np.zeros((n, 2))

    # drone on D, breathing slowly (periods divide 64 s so the loop closes)
    drone = np.zeros(n)
    for f, amp, det in ((note("D1"), 1.0, 0.07), (note("A1"), 0.45, 0.05), (note("D2"), 0.3, 0.09)):
        for d in (-det, det):
            drone += amp * saw(f + d, t, 8)
    breath = 0.75 + 0.25 * np.sin(2 * np.pi * t / 16.0)
    drone = lowpass(drone * breath, sr, 220, 2)
    out += pan(drone, -0.2) * 0.9 + pan(drone, 0.2) * 0.9

    # dissonant swells: a minor second rubbing inside a fifth, one chord per 16 s
    chords = [("D3", "Eb3", "A3"), ("C3", "Db3", "G3"), ("Bb2", "B2", "F3"), ("D3", "Eb3", "Ab3")]
    for i, chord in enumerate(chords):
        start = i * 16 * sr
        length = 16 * sr + 4 * sr  # overlaps into the next, wrapping at the end
        tt = np.arange(length) / sr
        shape = np.sin(np.pi * np.clip(tt / (length / sr), 0, 1)) ** 2
        voice = np.zeros(length)
        for j, nm in enumerate(chord):
            f = note(nm)
            vib = 1 + 0.003 * np.sin(2 * np.pi * (0.13 + 0.05 * j) * tt)
            phase = 2 * np.pi * np.cumsum(f * vib) / sr
            voice += np.sin(phase) + 0.35 * np.sin(2 * phase) + 0.15 * np.sin(3 * phase)
        voice = lowpass(voice * shape, sr, 900, 2) * 0.22
        place(out, pan(voice, (-0.5, 0.5, -0.3, 0.3)[i]), start)

    # the hull groaning: a slowly bending low resonance in filtered noise
    for k in range(5):
        length = int(rng.uniform(3.0, 5.0) * sr)
        tt = np.arange(length) / sr
        f0 = rng.uniform(55, 90)
        bend = f0 * (1 - 0.18 * tt / tt[-1])
        phase = 2 * np.pi * np.cumsum(bend) / sr
        tone = np.sin(phase) + 0.6 * np.sin(2.01 * phase) + 0.3 * np.sin(3.03 * phase)
        grit = bandpass(rng.standard_normal(length), sr, 80, 400) * 0.6
        g = (tone * 0.5 + grit) * np.sin(np.pi * tt / tt[-1]) ** 1.5
        place(out, pan(g * 0.35, rng.uniform(-0.8, 0.8)), int((k * 12.8 + rng.uniform(0, 4)) * sr))

    # creaks: a run of tiny friction clicks speeding up and slowing down
    for k in range(9):
        length = int(rng.uniform(0.5, 1.4) * sr)
        clicks = np.zeros(length)
        pos, rate = 0.0, rng.uniform(25, 60)
        while pos < length:
            clicks[int(pos)] = rng.uniform(0.5, 1.0)
            pos += sr / (rate * (1 + 0.6 * np.sin(np.pi * pos / length)))
        creak = resonance(clicks, sr, rng.uniform(500, 1400), 6) * 0.5
        place(out, pan(creak, rng.uniform(-1, 1)), int(rng.uniform(0, secs) * sr))

    # drips: a drop striking a puddle somewhere in the dark (a noise tick ringing briefly)
    for k in range(14):
        length = int(0.15 * sr)
        tick = rng.standard_normal(length) * np.exp(-np.arange(length) / sr * 300)
        drip = resonance(tick, sr, rng.uniform(900, 1600), 9)
        place(out, pan(drip * rng.uniform(0.03, 0.07), rng.uniform(-1, 1)), int(rng.uniform(0, secs) * sr))

    out = circular_convolve(out, reverb_ir(sr, 3.5, rng, stereo=True, damping=2500)) * 0.7 + out * 0.5
    out = highpass(out, sr, 28, 2)
    return rms_to(out, -20), sr


def music_combat():
    """Fight layer over the ship music: slow heavy drums, a low string pulse and a
    high trembling cluster. Same key (D), 32 s loop at 66 bpm."""
    sr, secs = SR_MUSIC, 32
    n = sr * secs
    t = np.arange(n) / sr
    rng = np.random.default_rng(23)
    out = np.zeros((n, 2))
    beats = int(round(secs / (60.0 / 66)))  # snap the beat so 32 s holds whole beats
    beat = secs / beats

    def drum(f_hi, f_lo, decay, noise_amt):
        length = int(1.2 * sr)
        tt = np.arange(length) / sr
        f = f_lo + (f_hi - f_lo) * np.exp(-tt * 18)
        body = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-tt / decay)
        skin = lowpass(rng.standard_normal(length), sr, 1800) * np.exp(-tt * 40) * noise_amt
        return body + skin

    # heartbeat pattern: boom-boom ... boom
    pattern = [0, 0.38, 2, 4, 4.38, 6, 6.5, 7]
    for bar in range(beats // 8):
        for p in pattern:
            hit = drum(120, 44, 0.45, 0.3) * (1.0 if p in (0, 4) else 0.6)
            place(out, pan(hit, rng.uniform(-0.15, 0.15)), int((bar * 8 + p) * beat * sr))

    # low strings: eighth notes on D with a fall to C# every other bar
    strings = np.zeros(n)
    for i in range(beats * 2):
        f = note("D2") if (i // 16) % 2 == 0 or i % 16 < 12 else note("C#2")
        length = int(beat / 2 * sr)
        tt = np.arange(length) / sr
        tone = saw(f, tt, 16) + 0.7 * saw(f * 1.004, tt, 16)
        place(strings, tone * env(length, 0.01, 0.18, sr, 3), int(i * beat / 2 * sr))
    strings = lowpass(strings, sr, 700, 2) * 0.16
    out += pan(strings, -0.25) + pan(strings, 0.25) * 0.8

    # high cluster, bowed tremolo, swelling over each 16 s half
    trem = np.zeros(n)
    for nm in ("D5", "Eb5", "A5"):
        f = note(nm)
        trem += saw(f * (1 + rng.uniform(-0.002, 0.002)), t, 6)
    trem *= 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 7.5 * t))  # tremolo bowing
    trem = lowpass(trem, sr, 3500, 2) * (np.sin(np.pi * (t % 16) / 16) ** 2) * 0.05
    out += pan(trem, 0.6) + pan(trem, -0.6) * 0.6

    out = circular_convolve(out, reverb_ir(sr, 2.5, rng, stereo=True, damping=3500)) * 0.5 + out * 0.8
    out = highpass(out, sr, 30, 2)
    return rms_to(out, -18), sr


def formants(x, sr, peaks):
    """Shape a buzzy source into a vowel: one resonant peak per (frequency, gain, q)."""
    return spectral(x, sr, lambda f: sum(g / np.sqrt(1.0 + (q * (f / fc - fc / f)) ** 2) for fc, g, q in peaks))


VOWEL_AH = ((700, 1.0, 5), (1150, 0.6, 6), (2600, 0.25, 8))
VOWEL_OO = ((320, 1.0, 5), (800, 0.45, 6), (2300, 0.12, 8))
VOWEL_OH = ((450, 1.0, 5), (800, 0.55, 6), (2600, 0.15, 8))


def music_hollow():
    """The Hollow: no ship metal any more. A sub drone breathing very slowly, a wordless
    choir on a rubbing cluster that slides between "ah" and "oo", wet groans, whispers
    just too quiet to understand, drips, all in a huge soft cave. Loops every 64 s.
    The heartbeat is left out on purpose: the heart in the level plays it, so it gets
    louder (and faster) as you get closer."""
    sr, secs = SR_MUSIC, 64
    n = sr * secs
    t = np.arange(n) / sr
    rng = np.random.default_rng(41)
    out = np.zeros((n, 2))

    # sub drone on D with a slow beating, swelling every 32 s
    sub = np.zeros(n)
    for f, amp in ((note("D1"), 1.0), (note("D1") * 1.006, 0.8), (note("A1"), 0.25)):
        sub += amp * np.sin(2 * np.pi * f * t)
    sub *= 0.7 + 0.3 * np.sin(2 * np.pi * t / 32.0 - np.pi / 2)
    out += pan(lowpass(sub, sr, 120, 2), 0.0) * 0.9

    # the choir: many slightly detuned voices per note, vowels morphing on 16 s cycles
    choir = {"ah": np.zeros(n), "oo": np.zeros(n)}
    for nm, amp in (("D3", 1.0), ("Eb3", 0.8), ("A3", 0.6), ("D4", 0.35), ("Ab3", 0.3)):
        f = note(nm)
        for v in range(4):
            vib = 1 + 0.004 * np.sin(2 * np.pi * rng.uniform(4.5, 6.0) * t + rng.uniform(0, 6.3))
            drift = 1 + rng.uniform(-0.004, 0.004)
            phase = 2 * np.pi * np.cumsum(f * drift * vib) / sr
            src = sum(np.sin(k * phase) / k for k in range(1, 14)) * amp
            choir["ah"] += src
            choir["oo"] += src
    ah = formants(choir["ah"], sr, VOWEL_AH)
    oo = formants(choir["oo"], sr, VOWEL_OO)
    morph = 0.5 + 0.5 * np.sin(2 * np.pi * t / 16.0)
    swell = 0.35 + 0.65 * np.sin(np.pi * (t % 32.0) / 32.0) ** 2
    voices = lowpass(ah * morph + oo * (1 - morph), sr, 3000, 2) * swell
    voices *= 0.035 / max(np.std(voices), 1e-9)
    out += pan(voices, -0.4) + pan(np.roll(voices, int(0.03 * sr)), 0.4)

    # groans: a huge voice-like thing, falling in pitch, growling
    for k in range(4):
        g = groan_voice(rng, sr, rng.uniform(4.0, 6.0), rng.uniform(42, 62))
        place(out, pan(g * 0.25, rng.uniform(-0.9, 0.9)), int((k * 16 + rng.uniform(2, 10)) * sr))

    # whispers: syllable-like bursts of breathy noise, panned wide and kept very quiet
    for k in range(10):
        length = int(rng.uniform(1.2, 2.4) * sr)
        tt = np.arange(length) / sr
        syll = np.abs(np.sin(np.pi * np.cumsum(rng.uniform(3.5, 6.5, length)) / sr)) ** 3
        breathy = formants(rng.standard_normal(length), sr, (VOWEL_AH, VOWEL_OO, VOWEL_OH)[k % 3])
        breathy = highpass(breathy, sr, 1200, 2) * syll * np.sin(np.pi * tt / tt[-1])
        breathy *= 0.012 / max(np.std(breathy), 1e-9)
        place(out, pan(breathy, rng.choice((-1, 1)) * rng.uniform(0.6, 1.0)), int(rng.uniform(0, secs) * sr))

    # wet drips and slow squelches somewhere in the dark
    for k in range(18):
        length = int(0.2 * sr)
        tick = rng.standard_normal(length) * np.exp(-np.arange(length) / sr * 250)
        drip = resonance(tick, sr, rng.uniform(700, 1400), 10)
        place(out, pan(drip * rng.uniform(0.02, 0.05), rng.uniform(-1, 1)), int(rng.uniform(0, secs) * sr))
    for k in range(5):
        sq = squelch(rng, sr, rng.uniform(0.4, 0.8))
        place(out, pan(sq * 0.05, rng.uniform(-1, 1)), int(rng.uniform(0, secs) * sr))

    out = circular_convolve(out, reverb_ir(sr, 5.0, rng, stereo=True, damping=1800, predelay=0.04)) * 0.8 + out * 0.4
    out = highpass(out, sr, 25, 2)
    return rms_to(out, -21), sr


MUSIC = {"music_ship": music_ship, "combat_layer": music_combat, "music_hollow": music_hollow}


# --- one-shots ---------------------------------------------------------------

def _room(x, rng, seconds=0.6, wet=0.25, damping=4000):
    return tail_convolve(x, reverb_ir(SR_SFX, seconds, rng, damping=damping)) * wet + np.pad(x, (0, int(seconds * SR_SFX)))


def step(floor, i):
    sr = SR_SFX
    rng = np.random.default_rng(100 * ("steel", "wood", "grate", "water", "flesh", "bone").index(floor) + i)
    n = int(0.35 * sr)
    tt = np.arange(n) / sr
    click = rng.standard_normal(n) * np.exp(-tt * 180)
    heel = np.sin(2 * np.pi * rng.uniform(70, 95) * tt) * np.exp(-tt * 40)
    if floor == "steel":
        modes = sum(np.sin(2 * np.pi * f * tt) * np.exp(-tt * d) * a for f, d, a in
                    ((rng.uniform(420, 520), 30, 0.5), (rng.uniform(1150, 1350), 45, 0.35),
                     (rng.uniform(2300, 2700), 60, 0.2), (rng.uniform(3800, 4300), 80, 0.1)))
        x = heel * 0.8 + bandpass(click, sr, 500, 6000) * 0.5 + modes * 0.3
        x = _room(x, rng, 0.7, 0.3)
    elif floor == "wood":
        knock = resonance(click, sr, rng.uniform(180, 260), 4) * 1.5
        x = heel + knock + bandpass(click, sr, 800, 3000) * 0.3
        x = _room(x, rng, 0.4, 0.15, 2500)
    elif floor == "grate":
        x = heel * 0.6
        for k in range(4):  # the grate bars rattling against each other
            at = int(rng.uniform(0.0, 0.05) * sr) + k * int(0.012 * sr)
            r = resonance(rng.standard_normal(int(0.08 * sr)) * np.exp(-np.arange(int(0.08 * sr)) / sr * 90),
                          sr, rng.uniform(1500, 3500), 12)
            x[at:at + r.shape[0]] += r[: n - at] * 0.6
        x = _room(x, rng, 0.7, 0.3)
    elif floor == "flesh":  # a boot sinking into wet flesh and peeling off it
        x = heel * 0.7 + squelch(rng, sr, 0.35)[:n] * 1.2
        x = _room(x, rng, 0.9, 0.12, 1800)
    elif floor == "bone":  # bones shifting and knocking together underfoot
        x = heel * 0.5 + squelch(rng, sr, 0.35)[:n] * 0.25
        for k in range(rng.integers(3, 7)):
            at = int(rng.uniform(0.0, 0.09) * sr) + k * int(rng.uniform(0.008, 0.02) * sr)
            m = int(0.06 * sr)
            bt = np.arange(m) / sr
            clack = sum(np.sin(2 * np.pi * rng.uniform(550, 2200) * bt) * np.exp(-bt * rng.uniform(60, 130))
                        for _ in range(3))
            clack += bandpass(rng.standard_normal(m), sr, 800, 3500) * np.exp(-bt * 350) * 0.5
            x[at:at + m] += clack[: n - at] * rng.uniform(0.25, 0.5)
        x = _room(x, rng, 0.9, 0.2, 3000)
    else:  # wading through shin-deep water
        x = wade(rng, sr)
        x = _room(x, rng, 0.5, 0.18, 2500)
    return normalize(fade(x, sr), -3)


def squelch(rng, sr, seconds):
    """Wet, sticky flesh: a soft press, then a crackling peel as it lets go, and a few
    small low bubbles of fluid."""
    n = int(seconds * sr)
    tt = np.arange(n) / sr
    press = lowpass(bandpass(rng.standard_normal(n), sr, 120, 1200), sr, 600, 1) * env(n, 0.015, 0.09, sr, 3)
    crackle = np.zeros(n)
    for _ in range(int(rng.integers(25, 45))):
        at = int((0.05 + abs(rng.normal(0, 0.05))) * sr)
        if at < n:
            crackle[at] += rng.uniform(-1, 1)
    peel = bandpass(crackle, sr, 600, 4000) * 2.0
    fluid = bubbles(rng, sr, n, 0.04, 0.05, 12, 250, 900, 0.12)
    return press + peel * np.exp(-tt * 6) + fluid


def groan_voice(rng, sr, seconds, f0):
    """A huge throat groaning: a buzzing low voice sliding down, a growl in it, shaped to "oh"."""
    n = int(seconds * sr)
    tt = np.arange(n) / sr
    contour = f0 * (1.15 - 0.3 * tt / tt[-1]) * (1 + 0.02 * np.sin(2 * np.pi * 0.7 * tt))
    wobble = lowpass(rng.standard_normal(n), sr, 8, 1)
    jitter = 1 + 0.01 * wobble / max(np.std(wobble), 1e-9)
    phase = 2 * np.pi * np.cumsum(contour * jitter) / sr
    buzz = sum(np.sin(k * phase) / k ** 0.8 for k in range(1, 30)) + 0.5 * np.sin(0.5 * phase)
    growl = 0.6 + 0.4 * np.sin(2 * np.pi * rng.uniform(18, 28) * tt)
    voice = formants(buzz * growl, sr, VOWEL_OH) + 0.2 * bandpass(rng.standard_normal(n), sr, 200, 900)
    shape = np.sin(np.pi * tt / tt[-1]) ** 1.2
    return lowpass(voice * shape, sr, 1800, 2) / max(np.std(voice), 1e-9) * 0.3


def heartbeat():
    """One lub-dub: two deep, muffled thumps, as if heard through flesh."""
    sr = SR_SFX
    rng = np.random.default_rng(900)
    n = int(1.1 * sr)
    tt = np.arange(n) / sr
    x = np.zeros(n)
    for at, f_hi, f_lo, amp in ((0.0, 70, 38, 1.0), (0.28, 80, 46, 0.7)):
        m = n - int(at * sr)
        bt = tt[:m]
        f = f_lo + (f_hi - f_lo) * np.exp(-bt * 20)
        thump = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-bt * 9) * env(m, 0.008, 0.2, sr, 2)
        thump += lowpass(rng.standard_normal(m), sr, 140, 2) * np.exp(-bt * 22) * 0.8
        x[int(at * sr):] += thump * amp
    x = np.tanh(x * 1.6)
    x = lowpass(x, sr, 300, 2)
    return normalize(fade(_room(x, rng, 1.2, 0.25, 600), sr, 0.001, 0.2), -1)


def breath(i):
    """Something breathing behind the wall: a long wet inhale, a rattling exhale."""
    sr = SR_SFX
    rng = np.random.default_rng(1000 + i)
    inhale, exhale = rng.uniform(1.1, 1.5), rng.uniform(1.4, 1.9)
    n = int((inhale + exhale + 0.3) * sr)
    tt = np.arange(n) / sr
    src = rng.standard_normal(n)
    a = np.clip(tt / inhale, 0, 1)
    in_env = np.where(tt < inhale, np.sin(np.pi * a) ** 1.5, 0)
    b = np.clip((tt - inhale - 0.15) / exhale, 0, 1)
    out_env = np.where(tt > inhale + 0.15, np.sin(np.pi * b) ** 1.2, 0)
    rattle = 0.55 + 0.45 * np.sin(2 * np.pi * rng.uniform(22, 34) * tt) ** 2
    hi = formants(src, sr, ((rng.uniform(450, 600), 1.0, 3), (rng.uniform(1300, 1700), 0.8, 4), (2800, 0.4, 5)))
    lo = formants(src, sr, ((rng.uniform(250, 380), 1.0, 3), (rng.uniform(800, 1000), 0.6, 4)))
    x = highpass(hi, sr, 300) * in_env * 0.8 + lo * out_env * rattle
    sq = squelch(rng, sr, 0.4)  # a wet catch in the throat as it turns to breathe out
    at = int((inhale + 0.05) * sr)
    x[at:at + sq.shape[0]] += sq[: n - at] * 0.15
    return normalize(fade(_room(lowpass(x, sr, 3500), rng, 1.0, 0.3, 1500), sr, 0.05, 0.3), -2)


def groan(i):
    sr = SR_SFX
    rng = np.random.default_rng(1100 + i)
    x = groan_voice(rng, sr, rng.uniform(4.0, 5.5), rng.uniform(40, 55))
    x = tail_convolve(x, reverb_ir(sr, 3.5, rng, damping=1200)) * 0.6 + np.pad(x, (0, int(3.5 * sr)))
    return normalize(fade(x, sr, 0.05, 0.5), -1)


def sting_fall():
    """The hold floor splitting under you: a tearing crack, a huge boom, the rush of
    falling in the dark, and the splash into black water."""
    sr = SR_SFX
    rng = np.random.default_rng(1200)
    n = int(5.0 * sr)
    tt = np.arange(n) / sr
    x = np.zeros(n)
    tear = np.zeros(int(0.9 * sr))
    pos = 0.0
    while pos < tear.shape[0]:
        tear[int(pos)] = rng.uniform(0.5, 1.0) * rng.choice((-1, 1))
        pos += sr / rng.uniform(80, 400)
    x[: tear.shape[0]] += resonance(tear, sr, 700, 3) * 0.8 + highpass(tear, sr, 2000) * 0.4
    crack = highpass(rng.standard_normal(n), sr, 400) * np.exp(-np.maximum(tt - 0.5, 0) * 30) * (tt > 0.5)
    boom = np.sin(2 * np.pi * np.cumsum(32 + 60 * np.exp(-np.maximum(tt - 0.5, 0) * 6)) / sr) \
        * np.exp(-np.maximum(tt - 0.5, 0) * 1.2) * (tt > 0.5)
    rumble = lowpass(rng.standard_normal(n), sr, 160, 2) * np.exp(-np.maximum(tt - 0.5, 0) * 0.8) * (tt > 0.5)
    rush = np.zeros(n)
    centres = 3000 * np.exp(-np.maximum(tt - 1.2, 0) * 1.3) + 300
    noise = rng.standard_normal(n)
    for k in range(10):
        lo, hi = int((1.2 + k * 0.2) * sr), int((1.4 + k * 0.2) * sr)
        c = centres[(lo + hi) // 2]
        w = np.zeros(n)
        w[lo:hi] = 1
        rush += bandpass(noise, sr, c * 0.6, c * 1.5) * lowpass(w, sr, 20, 1)
    rush *= np.sin(np.pi * np.clip((tt - 1.2) / 2.0, 0, 1)) ** 2 * 0.5
    x += crack * 0.9 + boom * 1.4 + rumble * 1.2 + rush
    splash_at = int(3.3 * sr)
    sp = wade(rng, sr) * 2.5 + bubbles(rng, sr, int(0.7 * sr), 0.0, 0.15, 300, 400, 3000, 0.08)
    sp = np.concatenate([sp, np.zeros(int(0.3 * sr))])[: n - splash_at]
    x[splash_at:splash_at + sp.shape[0]] += sp
    x = np.tanh(lowpass(x, sr, 5000, 1) * 1.3)
    x = tail_convolve(x, reverb_ir(sr, 3.0, rng, damping=1500)) * 0.4 + np.pad(x, (0, int(3.0 * sr)))
    return normalize(fade(x, sr, 0.002, 0.8), -1)


def sting_wake():
    """Waking in The Hollow: a low swell rising out of silence, a far groan, drips."""
    sr = SR_SFX
    rng = np.random.default_rng(1300)
    n = int(6.0 * sr)
    tt = np.arange(n) / sr
    swell = sum(np.sin(2 * np.pi * note(nm) * tt) * a for nm, a in (("D1", 1.0), ("A1", 0.4), ("Eb2", 0.25)))
    swell *= np.sin(np.pi * np.clip(tt / 5.5, 0, 1)) ** 2
    x = lowpass(swell, sr, 200) * 0.8
    g = groan_voice(rng, sr, 3.0, 45)
    x[int(1.5 * sr):int(1.5 * sr) + g.shape[0]] += g * 0.4
    for k in range(6):
        m = int(0.2 * sr)
        tick = rng.standard_normal(m) * np.exp(-np.arange(m) / sr * 250)
        at = int(rng.uniform(0.3, 5.5) * sr)
        x[at:at + m] += resonance(tick, sr, rng.uniform(700, 1400), 10)[: n - at] * 0.15
    x = tail_convolve(x, reverb_ir(sr, 4.0, rng, damping=1500)) * 0.5 + np.pad(x, (0, int(4.0 * sr)))
    return normalize(fade(x, sr, 0.05, 1.0), -2)


def bubbles(rng, sr, n, start, spread, count, f_lo, f_hi, level):
    """Many tiny bubbles, modelled like real ones (van den Doel): each rings at a pitch set
    by its size, dies within a few milliseconds and glides up slightly as it rises. Lots of
    small, short ones read as water; a few big, long chirps read as a cartoon."""
    out = np.zeros(n)
    for _ in range(count):
        f0 = np.exp(rng.uniform(np.log(f_lo), np.log(f_hi)))
        damp = 0.043 * f0 + 0.0014 * f0 ** 1.5
        m = min(int(6.0 / damp * sr), n)
        bt = np.arange(m) / sr
        f = f0 * (1 + 0.1 * damp * bt)
        b = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-damp * bt)
        at = int((start + abs(rng.normal(0, spread))) * sr)
        if at >= n:
            continue
        out[at:at + m] += b[: n - at] * level * rng.uniform(0.3, 1.0)
    return out


def wade(rng, sr):
    """A leg pushing through and a foot coming down in shin-deep water: a low wash of
    displaced water, a dense burst of small bubbles, the water slapping back, fading drops."""
    n = int(0.7 * sr)
    tt = np.arange(n) / sr
    push = lowpass(bandpass(rng.standard_normal(n), sr, 90, 1500), sr, 700, 1) * env(n, 0.06, 0.25, sr, 3)
    churn = bandpass(rng.standard_normal(n), sr, 600, 4000) * env(n, 0.02, 0.12, sr, 4) * 0.25
    burst = bubbles(rng, sr, n, 0.03, 0.05, 140, 1000, 4000, 0.08)
    slap_at = rng.uniform(0.14, 0.2)
    slap = bubbles(rng, sr, n, slap_at, 0.03, 60, 900, 2600, 0.07)
    slap += np.where(tt > slap_at, bandpass(rng.standard_normal(n), sr, 250, 1800)
                     * np.exp(-np.maximum(tt - slap_at, 0) * 14) * 0.18, 0)
    drops = bubbles(rng, sr, n, 0.3, 0.12, 8, 900, 2500, 0.05)
    return lowpass(push + churn + burst + slap + drops, sr, 5000, 1)


def hit(i):
    sr = SR_SFX
    rng = np.random.default_rng(300 + i)
    n = int(0.5 * sr)
    tt = np.arange(n) / sr
    thump = np.sin(2 * np.pi * np.cumsum(60 + 90 * np.exp(-tt * 30)) / sr) * np.exp(-tt * 14)
    crunch = bandpass(rng.standard_normal(n), sr, 300, 3500) * np.exp(-tt * 35)
    slap = highpass(rng.standard_normal(n), sr, 2000) * np.exp(-tt * 120)
    x = thump + crunch * 0.7 + slap * 0.3
    return normalize(fade(_room(x, rng, 0.5, 0.2), sr), -1)


def gunshot(i):
    sr = SR_SFX
    rng = np.random.default_rng(500 + i)
    n = int(0.8 * sr)
    tt = np.arange(n) / sr
    crack = highpass(rng.standard_normal(n), sr, 1200) * np.exp(-tt * 90)
    blast = lowpass(rng.standard_normal(n), sr, 900) * np.exp(-tt * 18)
    boom = np.sin(2 * np.pi * np.cumsum(45 + 120 * np.exp(-tt * 25)) / sr) * np.exp(-tt * 9)
    x = crack * 0.9 + blast * 0.9 + boom * 0.8
    x = np.tanh(x * 2.0)  # a little saturation
    return normalize(fade(_room(x, rng, 1.6, 0.35, 3000), sr, 0.0005, 0.3), -1)


def whoosh(i):
    sr = SR_SFX
    rng = np.random.default_rng(700 + i)
    n = int(0.45 * sr)
    tt = np.arange(n) / sr
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    centres = 500 + 1600 * np.sin(np.pi * tt / tt[-1]) ** 2  # sweeps up and back down
    for k in range(8):  # piecewise band-pass following the sweep
        lo, hi = k * n // 8, (k + 1) * n // 8
        seg = bandpass(noise, sr, centres[(lo + hi) // 2] * 0.6, centres[(lo + hi) // 2] * 1.6)
        w = np.zeros(n)
        w[lo:hi] = 1
        out += seg * lowpass(w, sr, 30, 1)
    out *= np.sin(np.pi * tt / tt[-1]) ** 2
    return normalize(fade(out, sr), -4)


def main():
    for name, fn in MUSIC.items():
        x, sr = fn()
        write(name, x, sr)
    for floor in ("steel", "wood", "grate", "water", "flesh", "bone"):
        for i in range(1, 5):
            write(f"step_{floor}_{i}", step(floor, i), SR_SFX)
    write("heartbeat", heartbeat(), SR_SFX)
    for i in range(1, 4):
        write(f"breath_{i}", breath(i), SR_SFX)
    for i in range(1, 3):
        write(f"groan_{i}", groan(i), SR_SFX)
    write("sting_fall", sting_fall(), SR_SFX)
    write("sting_wake", sting_wake(), SR_SFX)
    for i in range(1, 4):
        write(f"hit_{i}", hit(i), SR_SFX)
        write(f"gunshot_{i}", gunshot(i), SR_SFX)
    for i in range(1, 3):
        write(f"whoosh_{i}", whoosh(i), SR_SFX)


if __name__ == "__main__":
    main()
