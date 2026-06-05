#!/usr/bin/env python3
"""Reseat-repeatability gate: spread across N takes of ONE capsule.

    python3 repeatability.py cap3_reseat*.wav  [--sens 0.5] [--shape 0.5]
                                               [--write-mask band_mask.txt]

Pull and reseat the SAME capsule between every take, then pass all the takes
here. It reports how much the measurement moves across reseats -- that spread is
the hard floor on your match accuracy. If it's bigger than the capsule-to-capsule
differences you're chasing, you're measuring the jig, not the capsules.

PASS requires sensitivity range < --sens AND worst-band FR range < --shape
(defaults 0.5 dB). Run this and pass before you trust any capsule comparison.

--write-mask saves the bands whose reseat spread is under --shape to a file that
rank_pairs.py reads, so frequencies the jig can't reproduce repeatably (e.g. a
coupler notch that wanders with depth) are excluded from match scoring.
"""
import sys
import numpy as np
import analyze_caps as A


def main():
    args = sys.argv[1:]
    sens_th, shape_th = 0.5, 0.5
    mask_path = None
    if '--sens' in args:
        i = args.index('--sens'); sens_th = float(args[i + 1]); del args[i:i + 2]
    if '--shape' in args:
        i = args.index('--shape'); shape_th = float(args[i + 1]); del args[i:i + 2]
    mask_thresh = 1.0   # a band is matchable if its reseat spread is under your
                        # match tolerance (rank_pairs --shape), not the 0.5 gate
    if '--write-mask' in args:
        i = args.index('--write-mask'); mask_path = args[i + 1]; del args[i:i + 2]
    if '--mask-thresh' in args:
        i = args.index('--mask-thresh'); mask_thresh = float(args[i + 1]); del args[i:i + 2]
    if len(args) < 2:
        print(__doc__); sys.exit(1)

    takes = []
    for p in args:
        r = A.analyze(p)
        fr = r.get('sweep_fr') or r.get('pink_fr')
        takes.append({
            'file': p.split('/')[-1],
            'sens': r.get('tone_dbfs', float('nan')),
            'bands': np.array(A.sample_bands(fr)) if fr else np.full(len(A.FR_BANDS), np.nan),
        })

    sens = np.array([t['sens'] for t in takes])
    print(f"\n{len(takes)} reseat takes:")
    print(f"  {'file':<22} {'sens_1k':>9}")
    for t in takes:
        print(f"  {t['file']:<22} {t['sens']:>8.2f}")

    s_range = np.nanmax(sens) - np.nanmin(sens)
    print(f"\nsensitivity: mean {np.nanmean(sens):.2f}  range {s_range:.2f} dB  "
          f"sigma {np.nanstd(sens):.2f}")

    bands = np.vstack([t['bands'] for t in takes])           # takes x bands
    b_range = np.nanmax(bands, 0) - np.nanmin(bands, 0)       # per-band spread
    worst = np.nanmax(b_range)
    wf = A.FR_BANDS[int(np.nanargmax(b_range))]
    keep = b_range < shape_th
    print("\nper-band FR spread (range across reseats, dB):")
    for c, rg, k in zip(A.FR_BANDS, b_range, keep):
        bar = '#' * int(rg / 0.1)
        print(f"  {c:>5} Hz  {rg:4.1f}  {bar}{'' if k else '   <-- EXCLUDE'}")
    print(f"\nworst band: {worst:.1f} dB @ {wf} Hz")

    sens_ok = s_range < sens_th
    ok = sens_ok and keep.all()
    print(f"\nsensitivity: {'PASS' if sens_ok else 'FAIL'} "
          f"(range {s_range:.2f} < {sens_th})")
    print(f"FR: {int(keep.sum())}/{len(keep)} bands repeatable < {shape_th} dB")
    if not sens_ok:
        print("  -> level still drifts across reseats. Tighten the depth stop "
              "before trusting sensitivity matches.")

    if mask_path:
        mkeep = b_range < mask_thresh
        with open(mask_path, 'w') as fh:
            fh.write(f"# matchable FR bands (reseat spread < {mask_thresh} dB)\n")
            fh.write(f"# from {len(takes)} reseats; rank_pairs.py reads this\n")
            for c, rg in zip(A.FR_BANDS, b_range):
                line = f"{c}" if rg < mask_thresh else f"#{c}"
                tag = '' if rg < mask_thresh else '  # EXCLUDED'
                fh.write(f"{line}    # spread {rg:.1f} dB{tag}\n")
        excluded = [c for c, k in zip(A.FR_BANDS, mkeep) if not k]
        print(f"\nwrote mask -> {mask_path} (threshold {mask_thresh} dB): "
              f"{int(mkeep.sum())} bands kept, excluded: {excluded or 'none'}")


if __name__ == '__main__':
    main()
