#!/usr/bin/env python3
"""Generate the capsule-test WAV.

Usage:
    python3 make_test_wav.py [out.wav] [--sr 48000]

Writes a 16-bit stereo (dual-mono) WAV so it plays through whichever earbud
channel you've got. Play this through the jig, record the capsule off the
M10's mic-in, then run analyze_caps.py on the recording(s).
"""
import sys
import wave
import numpy as np
import testsig


def write_wav(path, x, sr):
    x = np.clip(x, -1.0, 1.0)
    i16 = (x * 32767.0).astype('<i2')
    stereo = np.column_stack([i16, i16]).reshape(-1)  # dual-mono
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())


def main():
    out = 'captest_signal.wav'
    sr = 48000
    args = sys.argv[1:]
    if '--sr' in args:
        i = args.index('--sr')
        sr = int(args[i + 1])
        del args[i:i + 2]
    if args:
        out = args[0]

    x = testsig.build_signal(sr)
    write_wav(out, x, sr)

    dur = len(x) / sr
    print(f"wrote {out}: {dur:.1f}s, {sr} Hz, 16-bit stereo dual-mono")
    print("segments: silence / pink noise / sweep 20-20k / 1kHz tone / silence")


if __name__ == '__main__':
    main()
