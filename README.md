# mic-capsule-matcher

Sort cheap electret capsules into matched pairs for a stereo mic. Built for
matching AOM-5024L capsules on a Sony PCM-M10, but none of it is specific to
that capsule or recorder.

Electret capsules ship with wide tolerances. The AOM-5024L is rated ±3 dB on
sensitivity. A stereo pair wants two capsules that agree to about 1 dB in level
and frequency response, so you measure a batch and sort. That's what this does.

## The method

No anechoic chamber, no calibrated reference mic. Matching only needs
*relative* measurements: play one known signal through the same earbud into
each capsule, and the earbud, the room, and the coupler all cancel when you
compare two capsules. What's left is the capsule difference.

The rig is a 3D-printed jig: capsule under test at one end, a cheap earbud at
the other, fixed distance. Play `captest_signal.wav` through the earbud, record
the capsule off your recorder's mic input, analyze.

The jig is parametric OpenSCAD in `m10_capsule_jig.scad`: a capsule well whose
floor is the depth stop, over a bore that couples to the earbud. Edit the
dimensions for your capsule and print. Keep the bore clearance tight (see the
seating note below); a loose well lets the capsule tilt and your reseats
scatter.

The test signal has three parts the analyzer finds on its own:

- Pink noise: averaged spectrum gives frequency response, no time alignment needed.
- Log sweep, 20 Hz to 20 kHz: deconvolved for a clean frequency response and a cross-check against the pink. The two should agree; when they don't, the measurement is bad.
- 1 kHz tone: the most repeatable sensitivity reference, plus a THD number.

Leading and trailing silence catch the noise floor.

## What actually matters

The capsules are the easy part. The rig is where it goes wrong.

**Jig seating repeatability is the bottleneck.** If reseating a capsule moves
the reading more than your match tolerance, you're measuring the jig. Run
`repeatability.py` on 4-6 reseats of one capsule and get the spread under
~0.5 dB before you trust any comparison. A tight bore with a positive depth
stop fixes it.

**Coupler resonances wander with seating depth.** A deep notch in the coupler
moves as insertion depth changes, so the bands around it scatter.
`repeatability.py --write-mask` finds those bands from your reseat data and
`rank_pairs.py` drops them from scoring.

**The mount is part of the match.** Two capsules matched to 0.4 dB still record
as an imbalanced pair if one sits in a rubber enclosure and the other is bare.
Mount both the same way.

**Clipping invalidates everything, silently.** The analyzer flags any take with
railed samples. Set gain so the sweep peaks around -6 to -12 dBFS.

## Requirements

Python 3 with `numpy` (no scipy). `play_test.sh` is macOS-only
(`osascript`/`afplay`, plus optional `SwitchAudioSource` from
`brew install switchaudio-osx` to pin the output device). Elsewhere, play
`captest_signal.wav` however you want at a fixed output level.

## Workflow

```bash
# 1. generate the test signal (or use the committed captest_signal.wav)
python3 make_test_wav.py

# 2. play it through the jig at a fixed level, record the capsule
./play_test.sh -d "External Headphones" -v 45 captest_signal.wav

# 3. validate the jig FIRST: reseat one capsule 4-6x, record each, then
python3 repeatability.py cap_seat*.wav --write-mask band_mask.txt
#    must pass (spread < ~0.5 dB) before any matching is trustworthy

# 4. measure the batch, two+ reseats each, log to CSV
python3 analyze_caps.py --csv caps.csv cap1_test*.wav cap2_test*.wav ...

# 5. rank every pairing (auto-uses band_mask.txt)
python3 rank_pairs.py caps.csv
```

`rank_pairs.py` averages takes per capsule (name files `<capsule>_testN.wav`)
and scores each pair on `dSens` (sensitivity gap) and `FRrms`
(frequency-response shape difference). Pass is under 1 dB on both.

## Tools

| file | what it does |
|------|--------------|
| `testsig.py` | shared signal definitions, so the sweep reference always matches what was played |
| `make_test_wav.py` | writes `captest_signal.wav` |
| `play_test.sh` | plays a WAV at a pinned macOS output device and volume, restores them after |
| `analyze_caps.py` | segments a recording; measures sensitivity, frequency response (pink and sweep), THD, noise floor; flags clipping; logs CSV |
| `repeatability.py` | reseat spread for one capsule (the jig gate); writes the trustworthy-band mask |
| `rank_pairs.py` | ranks all pairings from the CSV, masking jig-unreliable bands |

## Notes

`band_mask.txt` here is an example from one specific jig (its notch sits around
1.25-2.5 kHz). Regenerate it for your own jig with `repeatability.py
--write-mask`.

The frequency-response curves are dominated by the earbud and coupler, not the
capsule. That's fine: the earbud and coupler cancel in the capsule-to-capsule
difference, which is all matching needs. Don't read the absolute curve as the
capsule's response.

THD here is earbud plus capsule, usually earbud-dominated. Treat it as a
setup-consistency check rather than a capsule distortion spec.

MIT licensed.
