#!/usr/bin/env python3
"""Rank capsule pairings from a CSV logged by `analyze_caps.py --csv`.

    python3 rank_pairs.py caps.csv [--sens 1.0] [--shape 1.0] [--mask band_mask.txt]

Multiple rows for the same capsule (e.g. cap2_test1, cap2_test2) are averaged --
name your files <capsule>_testN.wav and takes collapse automatically. For every
pair of distinct capsules it reports:

    dSens   -- |sensitivity difference| at 1 kHz (dB)
    FRrms   -- RMS of the band-by-band FR-shape difference (dB), 200-2k normalized
    FRmax   -- worst single-band FR difference (dB)
    score   -- dSens + FRrms  (lower = better matched)

PASS requires dSens < --sens AND FRrms < --shape (defaults 1.0 dB each). The FR
shape is sensitivity-independent (each curve is normalized to its own 200-2k
mean), so dSens and FRrms capture level and timbre separately.

--mask FILE restricts the FR comparison to the trustworthy bands written by
repeatability.py --write-mask, so frequencies the jig can't reproduce repeatably
don't pollute the match score. Defaults to band_mask.txt if it exists.
"""
import csv
import sys
import math
from collections import defaultdict

FR_COLS = None  # discovered from the header


def load(path):
    global FR_COLS
    rows = []
    with open(path, newline='') as fh:
        r = csv.DictReader(fh)
        FR_COLS = [c for c in r.fieldnames if c.startswith('fr_')]
        for row in r:
            rows.append(row)
    return rows


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return float('nan')


def average_takes(rows):
    """Group rows by capsule id, average each numeric column across takes."""
    groups = defaultdict(list)
    for row in rows:
        groups[row['capsule']].append(row)
    caps = {}
    for cap, takes in groups.items():
        def avg(col):
            vals = [fnum(t.get(col)) for t in takes]
            vals = [v for v in vals if not math.isnan(v)]
            return sum(vals) / len(vals) if vals else float('nan')
        clip = max((fnum(t.get('clip_pct')) for t in takes), default=float('nan'))
        caps[cap] = {
            'n': len(takes),
            'sens': avg('sens_1k_dbfs'),
            'noise': avg('noise_dbfs'),
            'thd': avg('thd_pct'),
            'clip': clip,
            'fr': [avg(c) for c in FR_COLS],
        }
    return caps


def load_mask(path):
    """Read trustworthy band centers (uncommented integers) from a mask file."""
    keep = set()
    with open(path) as fh:
        for line in fh:
            line = line.split('#')[0].strip()
            if line.isdigit():
                keep.add(int(line))
    return keep


def col_keep(mask):
    """Boolean per FR column: keep if its band center is in the mask (or no mask)."""
    if mask is None:
        return [True] * len(FR_COLS)
    return [int(c[3:]) in mask for c in FR_COLS]


def fr_diff(a, b, keep):
    diffs = [x - y for x, y, k in zip(a['fr'], b['fr'], keep)
             if k and not (math.isnan(x) or math.isnan(y))]
    if not diffs:
        return float('nan'), float('nan')
    rms = math.sqrt(sum(d * d for d in diffs) / len(diffs))
    mx = max(diffs, key=abs)
    return rms, mx


def main():
    import os
    args = sys.argv[1:]
    sens_th, shape_th = 1.0, 1.0
    mask_path = None
    if '--sens' in args:
        i = args.index('--sens'); sens_th = float(args[i + 1]); del args[i:i + 2]
    if '--shape' in args:
        i = args.index('--shape'); shape_th = float(args[i + 1]); del args[i:i + 2]
    if '--mask' in args:
        i = args.index('--mask'); mask_path = args[i + 1]; del args[i:i + 2]
    if not args:
        print(__doc__); sys.exit(1)
    if mask_path is None and os.path.exists('band_mask.txt'):
        mask_path = 'band_mask.txt'

    caps = average_takes(load(args[0]))
    mask = load_mask(mask_path) if mask_path else None
    keep = col_keep(mask)
    if mask is not None:
        used = [int(c[3:]) for c, k in zip(FR_COLS, keep) if k]
        print(f"\nFR mask: {mask_path}  ({len(used)} bands used, "
              f"excluding {sorted(set(int(c[3:]) for c in FR_COLS) - set(used)) or 'none'})")
    names = sorted(caps)

    print(f"\n{len(names)} capsules ({sum(c['n'] for c in caps.values())} takes):")
    print(f"  {'capsule':<12} {'takes':>5} {'sens_1k':>9} {'noise':>7} {'thd%':>6}")
    for n in names:
        c = caps[n]
        flag = '  *** CLIPPED ***' if (c['clip'] == c['clip'] and c['clip'] > 0.02) else ''
        print(f"  {n:<12} {c['n']:>5} {c['sens']:>8.2f}  {c['noise']:>6.1f} {c['thd']:>6.2f}{flag}")
    clipped = [n for n in names if caps[n]['clip'] == caps[n]['clip'] and caps[n]['clip'] > 0.02]
    if clipped:
        print(f"\n  WARNING: {', '.join(clipped)} clipped -- re-record at lower gain; "
              f"their numbers are invalid.")

    if len(names) < 2:
        print("\nneed >=2 capsules to rank pairs."); return

    pairs = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = caps[names[i]], caps[names[j]]
            ds = abs(a['sens'] - b['sens'])
            rms, mx = fr_diff(a, b, keep)
            pairs.append((ds + rms, names[i], names[j], ds, rms, mx))
    pairs.sort(key=lambda p: p[0])

    print(f"\nPairings ranked (PASS = dSens<{sens_th} AND FRrms<{shape_th}):")
    print(f"  {'pair':<24} {'dSens':>6} {'FRrms':>6} {'FRmax':>6} {'score':>6}  verdict")
    for score, x, y, ds, rms, mx in pairs:
        ok = (ds < sens_th and rms < shape_th)
        v = 'PASS' if ok else 'fail'
        print(f"  {x+' + '+y:<24} {ds:>6.2f} {rms:>6.2f} {mx:>+6.1f} {score:>6.2f}  {v}")

    best = pairs[0]
    if best[3] < sens_th and best[4] < shape_th:
        print(f"\nbest pair: {best[1]} + {best[2]}  "
              f"(dSens {best[3]:.2f} dB, FRrms {best[4]:.2f} dB)")
    else:
        print("\nno pair passes both thresholds -- measure more capsules, or "
              "loosen with --sens / --shape")


if __name__ == '__main__':
    main()
