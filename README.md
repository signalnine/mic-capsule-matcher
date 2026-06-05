# mic-capsule-matcher

Tools for sorting cheap electret capsules into matched pairs for a stereo
microphone. Built while matching AOM-5024L capsules for a Sony PCM-M10, but
nothing here is specific to that capsule or recorder.

Electret capsules ship with wide tolerances — the AOM-5024L is spec'd at
±3 dB sensitivity. For a stereo pair you want two that agree to about 1 dB in
both level and frequency response. That means measuring a batch and sorting.
This is the measurement and sorting toolchain.

## The method

You don't need an anechoic chamber or a calibrated reference mic. The trick is
that matching only needs *relative* measurements: play one known signal through
the same earbud into each capsule under test, and the earbud's own response,
the room, and the coupler all cancel when you compare two capsules. What's left
is the difference between the capsules.

The rig is a 3D-printed jig: the capsule under test at one end, a cheap earbud
at the other, fixed distance. Play `captest_signal.wav` through the earbud,
record the capsule off your recorder's mic input, and analyze.

The test signal has three parts the analyzer finds automatically:

- **Pink noise** — averaged spectrum gives frequency response without needing
  time alignment.
- **Log sweep (20 Hz–20 kHz)** — deconvolved for a clean frequency response and
  a cross-check against the pink result. The two should agree; if they don't,
  your measurement is bad.
- **1 kHz tone** — the most repeatable sensitivity reference and a THD number.

Leading/trailing silence captures the noise floor.

## What matters (hard-won)

The capsules are the easy part. The measurement rig is where it goes wrong:

- **Jig seating repeatability is the real bottleneck.** If reseating a capsule
  moves the reading more than your match tolerance, you're measuring the jig,
  not the capsule. Run `repeatability.py` on 4–6 reseats of one capsule and get
  the spread under ~0.5 dB *before* trusting any capsule-to-capsule comparison.
  A tight bore with a positive depth stop is the fix.
- **Coupler resonances wander with seating.** A deep notch in the coupler moves
  with insertion depth, so the bands around it are unreliable. `repeatability.py
  --write-mask` finds those bands from your reseat data and `rank_pairs.py`
  excludes them from scoring.
- **The mount is part of the match.** Two capsules matched to 0.4 dB will still
  record as an imbalanced pair if one is in a rubber enclosure and the other is
  bare. Mount both identically.
- **Watch your record level.** Clipping silently invalidates everything. The
  analyzer flags any take with railed samples; set gain so the sweep peaks
  around −6 to −12 dBFS.

## Requirements

- Python 3 with `numpy` (no scipy needed)
- `play_test.sh` is macOS-specific (`osascript`/`afplay`; optional
  `SwitchAudioSource` via `brew install switchaudio-osx` for device pinning).
  On other platforms, play `captest_signal.wav` however you like at a fixed,
  repeatable output level.

## Workflow

```bash
# 1. generate the test signal (or use the committed captest_signal.wav)
python3 make_test_wav.py

# 2. play it through the jig at a fixed level, record the capsule
./play_test.sh -d "External Headphones" -v 45 captest_signal.wav

# 3. validate the jig FIRST: reseat one capsule 4-6x, record each, then
python3 repeatability.py cap_seat*.wav --write-mask band_mask.txt
#    -> must pass (spread < ~0.5 dB) before you trust any matching

# 4. measure the batch, two+ reseats each, log to a CSV
python3 analyze_caps.py --csv caps.csv cap1_test*.wav cap2_test*.wav ...

# 5. rank every pairing (auto-uses band_mask.txt)
python3 rank_pairs.py caps.csv
```

`rank_pairs.py` averages multiple takes per capsule (name files
`<capsule>_testN.wav`) and scores each pair by `dSens` (sensitivity gap) and
`FRrms` (frequency-response shape difference). A pass is under 1 dB on both.

## Tools

| file | what it does |
|------|--------------|
| `testsig.py` | shared signal definitions (pink/sweep/tone) used by the generator and analyzer so the sweep reference always matches what was played |
| `make_test_wav.py` | writes `captest_signal.wav` |
| `play_test.sh` | plays a WAV at a pinned macOS output device + volume, restores them after |
| `analyze_caps.py` | segments a recording, measures sensitivity, frequency response (pink + sweep), THD, noise floor; flags clipping; logs CSV rows |
| `repeatability.py` | spread across N reseats of one capsule — the jig gate; writes the trustworthy-band mask |
| `rank_pairs.py` | ranks all capsule pairings from the CSV, masking jig-unreliable bands |

## Notes

- `band_mask.txt` in this repo is an example from one specific jig (its notch
  sits around 1.25–2.5 kHz). **Regenerate it for your own jig** with
  `repeatability.py --write-mask`.
- Frequency-response curves are dominated by the earbud and coupler, not the
  capsule — that's fine, because the earbud/coupler cancel in the
  capsule-to-capsule *difference*, which is all matching needs. Don't read the
  absolute curve as the capsule's response.
- THD here is earbud + capsule combined and usually earbud-dominated. It's a
  setup-consistency check, not a capsule distortion spec.

MIT licensed.
