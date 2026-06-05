"""Shared test-signal definitions for capsule matching.

Both the generator (make_test_wav.py) and the analyzer (analyze_caps.py)
import from here so the sweep reference used for deconvolution is guaranteed
to match the sweep that was played.

Layout of the generated WAV (times in seconds):

    [ lead silence ][ pink noise ][ gap ][ log sweep ][ gap ][ 1k tone ][ tail silence ]

The analyzer does NOT rely on these exact times in a recording -- it finds the
three active regions by energy and classifies each by spectral character. The
only thing that must match between generator and analyzer is the sweep math,
which lives in ess()/ess_at_sr().
"""

import numpy as np

# --- signal parameters (the analyzer needs these to rebuild the sweep ref) ---
F1 = 20.0          # sweep start (Hz)
F2 = 20000.0       # sweep end (Hz)
SWEEP_T = 12.0     # sweep duration (s)
PINK_T = 12.0      # pink-noise duration (s)
TONE_F = 1000.0    # THD / sensitivity tone (Hz)
TONE_T = 4.0       # tone duration (s)
LEAD_SIL = 1.0     # leading silence (s) -- also the noise-floor capture
GAP = 1.5          # gap between segments (s)
TAIL_SIL = 1.0     # trailing silence (s)
FADE = 0.020       # raised-cosine fade on each segment edge (s)

PEAK = 0.5         # ~-6 dBFS digital headroom for every segment


def _fade_window(n, nf):
    w = np.ones(n)
    if nf > 0:
        r = np.sin(np.linspace(0, np.pi / 2, nf)) ** 2
        w[:nf] = r
        w[-nf:] = r[::-1]
    return w


def pink_noise(dur, sr, seed=12345):
    """Stationary pink noise, band-limited to [F1, F2], peak-normalized."""
    n = int(dur * sr)
    rng = np.random.default_rng(seed)
    X = rng.standard_normal(n // 2 + 1) + 1j * rng.standard_normal(n // 2 + 1)
    f = np.fft.rfftfreq(n, 1 / sr)
    scale = np.zeros_like(f)
    scale[1:] = 1.0 / np.sqrt(f[1:])          # -3 dB/oct = pink
    band = (f >= F1) & (f <= F2)
    scale[~band] = 0.0
    x = np.fft.irfft(X * scale, n)
    x /= np.max(np.abs(x)) + 1e-12
    x *= _fade_window(n, int(FADE * sr))
    return (x * PEAK).astype(np.float64)


def ess_at_sr(sr, dur=SWEEP_T, f1=F1, f2=F2, fade=FADE):
    """Farina exponential sine sweep, synthesized at an arbitrary sample rate.

    Returned at full PEAK amplitude. The analyzer calls this at the *recording's*
    sample rate to build the deconvolution reference -- no resampling needed."""
    n = int(dur * sr)
    t = np.arange(n) / sr
    L = dur / np.log(f2 / f1)
    s = np.sin(2 * np.pi * f1 * L * (np.exp(t / L) - 1.0))
    s *= _fade_window(n, int(fade * sr))
    return s.astype(np.float64)


def sweep(sr):
    return ess_at_sr(sr) * PEAK


def tone(dur, sr, f=TONE_F):
    n = int(dur * sr)
    t = np.arange(n) / sr
    x = np.sin(2 * np.pi * f * t)
    x *= _fade_window(n, int(FADE * sr))
    return (x * PEAK).astype(np.float64)


def build_signal(sr):
    """Assemble the full mono test signal at sample rate `sr`."""
    sil = lambda d: np.zeros(int(d * sr))
    parts = [
        sil(LEAD_SIL),
        pink_noise(PINK_T, sr),
        sil(GAP),
        sweep(sr),
        sil(GAP),
        tone(TONE_T, sr),
        sil(TAIL_SIL),
    ]
    return np.concatenate(parts)
