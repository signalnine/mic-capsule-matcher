#!/usr/bin/env python3
"""Analyze one or two capsule recordings of captest_signal.wav.

Usage:
    python3 analyze_caps.py cap1_rec.wav                # characterize one
    python3 analyze_caps.py cap1_rec.wav cap2_rec.wav   # match a pair
    python3 analyze_caps.py --csv caps.csv cap*_rec.wav # log a row per file
                                                        # (then: rank_pairs.py caps.csv)

It auto-locates the three test segments (pink / sweep / 1k tone) in each
recording by energy + spectral character, then reports:

  * sensitivity   -- from the 1 kHz tone (primary) and pink RMS
  * frequency response -- 1/12-oct, from pink AND from the sweep (cross-check)
  * THD           -- from the 1 kHz tone
  * noise floor   -- from the leading silence

With two files it adds the capsule2 - capsule1 deltas: a single sensitivity
number and the band-by-band FR difference. Those deltas are what you match on,
and the playback chain (earbud, jig, room) cancels out of them.
"""
import csv
import os
import sys
import wave
import numpy as np
import testsig


# 1/3-octave band centers spanning the trustworthy band (set by the earbud/jig
# usable range and the reseat-repeatability test). Logged per capsule for matching.
FR_BANDS = [160, 200, 250, 315, 400, 500, 630, 800, 1000, 1250,
            1600, 2000, 2500, 3150, 4000, 5000, 6300]


# ----------------------------- WAV loading -----------------------------------

def load_wav(path):
    with wave.open(path, 'rb') as w:
        ch, sw, sr, n = (w.getnchannels(), w.getsampwidth(),
                         w.getframerate(), w.getnframes())
        raw = w.readframes(n)
    if sw == 2:
        a = np.frombuffer(raw, '<i2').astype(np.float64) / 32768.0
    elif sw == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        v = np.where(v & 0x800000, v - 0x1000000, v)
        a = v.astype(np.float64) / 0x800000
    elif sw == 4:
        a = np.frombuffer(raw, '<i4').astype(np.float64) / 2147483648.0
    else:
        raise ValueError(f"unsupported sample width {sw}")
    a = a.reshape(-1, ch)
    # pick the channel with the most energy (the one the capsule is on)
    rms = np.sqrt((a ** 2).mean(0))
    return a[:, int(np.argmax(rms))], sr


# ----------------------------- segmentation ----------------------------------

def db(x):
    return 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-15)


def find_segments(x, sr):
    """Return list of (start, end) sample indices for active regions."""
    win = max(1, int(0.02 * sr))
    env = np.sqrt(np.convolve(x ** 2, np.ones(win) / win, 'same'))
    edb = 20 * np.log10(env + 1e-12)
    floor = np.percentile(edb, 10)
    peak = np.percentile(edb, 99)
    thr = max(floor + 12.0, peak - 40.0)
    active = edb > thr
    # fill short gaps, drop short blips
    segs = []
    i = 0
    N = len(active)
    min_gap = int(0.4 * sr)
    min_len = int(1.0 * sr)
    while i < N:
        if active[i]:
            j = i
            while j < N and active[j]:
                j += 1
            # look ahead: bridge a short silence
            k = j
            while k < N and not active[k] and (k - j) < min_gap:
                k += 1
            if k < N and active[k]:
                while j < N and active[j]:
                    j += 1
            if (j - i) >= min_len:
                segs.append((i, j))
            i = j
        else:
            i += 1
    # merge segments separated by < min_gap
    merged = []
    for s in segs:
        if merged and s[0] - merged[-1][1] < min_gap:
            merged[-1] = (merged[-1][0], s[1])
        else:
            merged.append(list(s))
    return [tuple(m) for m in merged]


def classify(seg, sr):
    """Label a segment as 'pink', 'sweep', or 'tone' by spectral character.

    Tone -> energy concentrated in one bin. Sweep -> spectral centroid rises
    strongly across the segment. Pink -> broadband, stationary. Concentration
    is robust to the earbud/jig coloring the pink down to a narrow band, which
    spectral-flatness was not."""
    s, e = seg
    x = x_global[s:e]
    X = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    conc = X.max() / (X.sum() + 1e-12)        # one bin dominates -> tone
    third = len(x) // 3
    cen = []
    for k in range(3):
        xc = x[k * third:(k + 1) * third]
        Xc = np.abs(np.fft.rfft(xc * np.hanning(len(xc))))
        f = np.fft.rfftfreq(len(xc), 1 / sr)
        cen.append(np.sum(f * Xc) / (np.sum(Xc) + 1e-12))
    drift = (cen[2] - cen[0]) / (cen[0] + 1e-9)
    if conc > 0.02:
        return 'tone'
    if drift > 0.8:
        return 'sweep'
    return 'pink'


# ----------------------------- measurements ----------------------------------

def _npow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def welch(x, sr, nfft=16384):
    """Averaged power spectrum (magnitude) via Welch."""
    hop = nfft // 2
    win = np.hanning(nfft)
    acc = np.zeros(nfft // 2 + 1)
    cnt = 0
    for i in range(0, len(x) - nfft, hop):
        X = np.abs(np.fft.rfft(x[i:i + nfft] * win))
        acc += X ** 2
        cnt += 1
    if cnt == 0:
        X = np.abs(np.fft.rfft(np.pad(x, (0, nfft - len(x))) * win))
        acc = X ** 2
        cnt = 1
    f = np.fft.rfftfreq(nfft, 1 / sr)
    return f, np.sqrt(acc / cnt)


def pink_fr(rec, sr):
    """System FR from the pink segment: measured spectrum / source spectrum.

    Source pink magnitude is proportional to 1/sqrt(f) within [F1, F2], so the
    system response is the measured magnitude * sqrt(f) over that band."""
    f, m = welch(rec, sr)
    band = (f >= testsig.F1) & (f <= testsig.F2)
    h = np.full_like(m, np.nan)
    h[band] = m[band] * np.sqrt(f[band])
    return f, h


def sweep_fr(rec, sr, tail=0.5, reg=1e-3):
    """System FR via aligned spectral division.

    Matched-filter the recording against the played sweep to find the onset,
    window the full aligned sweep (+ ringing tail), then H = R/S regularized.
    Exact regardless of sweep shape, and robust to the quiet low-frequency
    start that an energy threshold would truncate."""
    ref = testsig.ess_at_sr(sr)
    if len(rec) < len(ref):
        return np.array([0.0]), np.array([np.nan])  # window can't hold the sweep
    nfft = _npow2(len(rec) + len(ref))
    xc = np.fft.irfft(np.fft.rfft(rec, nfft) * np.conj(np.fft.rfft(ref, nfft)), nfft)
    # only positive lags where a full sweep still fits inside rec
    maxlag = len(rec) - len(ref)
    d = int(np.argmax(np.abs(xc[:maxlag + 1])))
    W = len(ref) + int(tail * sr)
    seg = rec[d:d + W]
    if len(seg) < W:
        seg = np.pad(seg, (0, W - len(seg)))
    S = np.fft.rfft(ref, W)
    R = np.fft.rfft(seg, W)
    P = np.abs(S) ** 2
    H = R * np.conj(S) / (P + reg * P.max())
    f = np.fft.rfftfreq(W, 1 / sr)
    return f, np.abs(H)


def oct_smooth(f, mag, frac=12, fmin=30, fmax=20000):
    """Fractional-octave smooth onto a FIXED frequency grid.

    Bands with no valid (finite) data become NaN rather than being dropped, so
    every curve shares the same fc grid and can be compared index-by-index."""
    fc = fmin * 2 ** (np.arange(0, frac * np.log2(fmax / fmin)) / frac)
    e = np.full(len(fc), np.nan)
    for i, c in enumerate(fc):
        lo, hi = c / 2 ** (1 / (2 * frac)), c * 2 ** (1 / (2 * frac))
        m = (f >= lo) & (f < hi) & np.isfinite(mag)
        if m.any():
            e[i] = 20 * np.log10(np.sqrt(np.mean(mag[m] ** 2)) + 1e-15)
    return fc, e


def thd(x, sr, f0=testsig.TONE_F):
    """THD from the tone segment (fundamental + 5 harmonics)."""
    x = x[len(x) // 4: -len(x) // 4]          # steady middle
    X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1 / sr)

    def amp(fq):
        m = (f >= fq - 8) & (f <= fq + 8)
        return X[m].max() if m.any() else 0.0
    fund = amp(f0)
    harm = np.array([amp(f0 * k) for k in range(2, 7)])
    if fund <= 0 or f0 * 2 > sr / 2:
        return float('nan')
    return 100.0 * np.sqrt(np.sum(harm ** 2)) / fund


# ----------------------------- per-file pipeline -----------------------------

def analyze(path):
    global x_global
    x_global, sr = load_wav(path)
    segs = find_segments(x_global, sr)
    order = ['pink', 'sweep', 'tone']
    if len(segs) == 3:
        # layout is fixed and reliable -> assign by time order
        labels = dict(zip(order, segs))
        cl = [classify(s, sr) for s in segs]
        if cl != order:
            print(f"  [warn] {path}: segment classes {cl} != {order}; "
                  f"trusting time order, but check the recording")
    else:
        labels = {}
        for s in segs:
            labels[classify(s, sr)] = s
        print(f"  [warn] {path}: found {len(segs)} active segments, expected 3 "
              f"(pink/sweep/tone) -- recording may be clipped or noisy")

    out = {'path': path, 'sr': sr, 'labels': {k: (v[0] / sr, v[1] / sr)
                                              for k, v in labels.items()}}

    # clipping check -- railed samples invalidate sensitivity, THD, and FR
    peak = float(np.max(np.abs(x_global)))
    out['peak_dbfs'] = 20 * np.log10(peak + 1e-12)
    out['clip_pct'] = 100.0 * np.mean(np.abs(x_global) > 0.985)
    if out['clip_pct'] > 0.02 or peak >= 0.999:
        out['clipped'] = True
        print(f"  [WARN] {path}: CLIPPING -- peak {out['peak_dbfs']:.1f} dBFS, "
              f"{out['clip_pct']:.2f}% of samples railed. Numbers are invalid; "
              f"lower the M10 input gain and re-record.")

    # noise floor from leading silence (before first segment)
    if segs:
        lead = x_global[:segs[0][0]]
        out['noise_dbfs'] = db(lead) if len(lead) > sr * 0.2 else float('nan')

    if 'tone' in labels:
        s, e = labels['tone']
        out['tone_dbfs'] = db(x_global[s:e])
        out['thd_pct'] = thd(x_global[s:e], sr)
    if 'pink' in labels:
        s, e = labels['pink']
        out['pink_dbfs'] = db(x_global[s:e])
        f, m = pink_fr(x_global[s:e], sr)
        out['pink_fr'] = oct_smooth(f, m)
    if 'sweep' in labels:
        s, e = labels['sweep']
        # give sweep_fr a region that holds the WHOLE sweep, not the
        # energy-thresholded core (its quiet 20 Hz start falls below threshold).
        lo = labels['pink'][1] if 'pink' in labels else max(0, s - int(4 * sr))
        hi = labels['tone'][0] if 'tone' in labels else min(len(x_global), e + int(2 * sr))
        f, m = sweep_fr(x_global[lo:hi], sr)
        out['sweep_fr'] = oct_smooth(f, m)
    return out


def fmt_fr(fc, e, ref0=True):
    """Normalize a FR curve to its 200-2000 Hz average and render a sparse table."""
    band = (fc >= 200) & (fc <= 2000)
    e = e - np.nanmean(e[band])
    rows = []
    for c, v in zip(fc[::4], e[::4]):
        if not np.isfinite(v):
            continue
        bar = '#' * max(0, int((v + 24) / 1.5))
        rows.append(f"  {c:8.0f} Hz  {v:+6.1f}  {bar}")
    return '\n'.join(rows)


def report_one(r):
    print(f"\n=== {r['path']}  ({r['sr']} Hz) ===")
    print(f"  segments found: {', '.join(f'{k} @ {v[0]:.1f}-{v[1]:.1f}s' for k, v in r['labels'].items())}")
    if 'noise_dbfs' in r:
        print(f"  noise floor (lead silence): {r['noise_dbfs']:6.1f} dBFS")
    if 'tone_dbfs' in r:
        print(f"  1kHz sensitivity:           {r['tone_dbfs']:6.1f} dBFS   THD: {r.get('thd_pct', float('nan')):.2f}%")
    if 'pink_dbfs' in r:
        print(f"  pink-noise RMS:             {r['pink_dbfs']:6.1f} dBFS")
    if 'sweep_fr' in r:
        print("  frequency response (sweep, normalized to 200-2k):")
        print(fmt_fr(*r['sweep_fr']))
    return r


def report_pair(a, b):
    print("\n" + "=" * 52)
    print("MATCH REPORT  (capsule2 - capsule1)")
    print("=" * 52)
    if 'tone_dbfs' in a and 'tone_dbfs' in b:
        d = b['tone_dbfs'] - a['tone_dbfs']
        verdict = 'EXCELLENT' if abs(d) < 1 else 'OK' if abs(d) < 2 else 'POOR'
        print(f"  sensitivity delta @1kHz: {d:+.2f} dB   [{verdict} -- aim < 1 dB]")
    # FR difference from whichever method both have
    for key, name in (('sweep_fr', 'sweep'), ('pink_fr', 'pink')):
        if key in a and key in b:
            fca, ea = a[key]
            fcb, eb = b[key]
            # same fc grid (fixed by oct_smooth) -> safe to align by index
            n = min(len(fca), len(fcb))
            fca, ea, eb = fca[:n], ea[:n], eb[:n]
            band = (fca >= 200) & (fca <= 2000)
            ea = ea - np.nanmean(ea[band])
            eb = eb - np.nanmean(eb[band])
            diff = eb - ea
            rng = (fca >= 50) & (fca <= 18000) & np.isfinite(diff)
            spread = diff[rng].max() - diff[rng].min()
            print(f"\n  FR difference ({name}), normalized @200-2k, max spread {spread:.1f} dB:")
            for c, dv in zip(fca[::4], diff[::4]):
                if c < 40 or c > 19000 or not np.isfinite(dv):
                    continue
                bar = '+' * int(max(0, dv) / 0.5) + '-' * int(max(0, -dv) / 0.5)
                print(f"    {c:8.0f} Hz  {dv:+5.1f}  {bar}")
            break


def capsule_id(path):
    """Capsule name from a filename: strip extension and a trailing _testN/-N."""
    base = os.path.splitext(os.path.basename(path))[0]
    import re
    return re.sub(r'[._-](test)?\d+$', '', base)


def sample_bands(fr, centers=FR_BANDS):
    """Normalize a FR curve to its 200-2k mean and sample at band centers."""
    fc, e = fr
    band = (fc >= 200) & (fc <= 2000)
    e = e - np.nanmean(e[band])
    out = []
    for c in centers:
        i = int(np.argmin(np.abs(fc - c)))
        out.append(e[i] if np.isfinite(e[i]) else float('nan'))
    return out


def feature_row(r):
    row = {
        'capsule': capsule_id(r['path']),
        'file': os.path.basename(r['path']),
        'sens_1k_dbfs': round(r.get('tone_dbfs', float('nan')), 2),
        'pink_rms_dbfs': round(r.get('pink_dbfs', float('nan')), 2),
        'thd_pct': round(r.get('thd_pct', float('nan')), 3),
        'noise_dbfs': round(r.get('noise_dbfs', float('nan')), 1),
        'peak_dbfs': round(r.get('peak_dbfs', float('nan')), 1),
        'clip_pct': round(r.get('clip_pct', float('nan')), 2),
    }
    fr = r.get('sweep_fr') or r.get('pink_fr')
    bands = sample_bands(fr) if fr else [float('nan')] * len(FR_BANDS)
    for c, v in zip(FR_BANDS, bands):
        row[f'fr_{c}'] = round(v, 2) if np.isfinite(v) else ''
    return row


def append_csv(path, rows):
    fields = (['capsule', 'file', 'sens_1k_dbfs', 'pink_rms_dbfs', 'thd_pct',
               'noise_dbfs', 'peak_dbfs', 'clip_pct'] + [f'fr_{c}' for c in FR_BANDS])
    exists = os.path.exists(path)
    with open(path, 'a', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if not exists:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    argv = sys.argv[1:]
    csv_path = None
    if '--csv' in argv:
        i = argv.index('--csv')
        csv_path = argv[i + 1]
        del argv[i:i + 2]
    paths = argv
    if not paths:
        print(__doc__)
        sys.exit(1)
    results = [report_one(analyze(p)) for p in paths]
    if csv_path:
        append_csv(csv_path, [feature_row(r) for r in results])
        print(f"\nlogged {len(results)} row(s) -> {csv_path}")
    elif len(results) == 2:
        report_pair(*results)


if __name__ == '__main__':
    main()
