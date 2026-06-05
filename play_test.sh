#!/usr/bin/env bash
# Play a test WAV at a fixed output device + level for repeatable measurements.
#
#   ./play_test.sh                          # captest_signal.wav at vol 50
#   ./play_test.sh somefile.wav             # a specific file at vol 50
#   ./play_test.sh -v 40 captest_signal.wav # set output volume to 40 (0-100)
#   ./play_test.sh -d "External Headphones" # force output device, then play
#   ./play_test.sh -l                       # list output devices and exit
#   ./play_test.sh -k ...                   # keep volume/device (don't restore)
#
# macOS "output volume" (0-100) is nonlinear but perfectly repeatable, which is
# all that matters here. Use a WIRED output: Bluetooth devices keep their own
# internal volume that this does not control, so they're not repeatable.
#
# Device switching needs SwitchAudioSource: brew install switchaudio-osx

set -euo pipefail

VOL=30
KEEP=0
DEVICE=""
FILE="captest_signal.wav"
SAS=$(command -v SwitchAudioSource || true)

while [[ $# -gt 0 ]]; do
  case "$1" in
    -v|--volume) VOL="$2"; shift 2 ;;
    -d|--device) DEVICE="$2"; shift 2 ;;
    -k|--keep)   KEEP=1; shift ;;
    -l|--list)
      if [[ -n "$SAS" ]]; then echo "output devices:"; "$SAS" -a -t output
      else echo "SwitchAudioSource not installed: brew install switchaudio-osx"; fi
      exit 0 ;;
    -h|--help)   sed -n '2,18p' "$0"; exit 0 ;;
    *)           FILE="$1"; shift ;;
  esac
done

if [[ ! -f "$FILE" ]]; then echo "no such file: $FILE" >&2; exit 1; fi
if ! [[ "$VOL" =~ ^[0-9]+$ ]] || (( VOL < 0 || VOL > 100 )); then
  echo "volume must be 0-100, got: $VOL" >&2; exit 1
fi

# --- output device (optional) ---
orig_dev=""
if [[ -n "$DEVICE" ]]; then
  if [[ -z "$SAS" ]]; then
    echo "can't set device -- SwitchAudioSource not installed." >&2
    echo "  brew install switchaudio-osx" >&2
    exit 1
  fi
  if ! "$SAS" -a -t output | grep -qxF "$DEVICE"; then
    echo "no output device named: $DEVICE" >&2
    echo "available:" >&2; "$SAS" -a -t output | sed 's/^/  /' >&2
    exit 1
  fi
  orig_dev=$("$SAS" -c -t output)
  "$SAS" -s "$DEVICE" -t output >/dev/null
fi

# --- volume ---
orig=$(osascript -e 'output volume of (get volume settings)')
muted=$(osascript -e 'output muted of (get volume settings)')

restore() {
  if [[ "$KEEP" -eq 0 ]]; then
    osascript -e "set volume output volume $orig" \
              -e "set volume output muted $muted"
    [[ -n "$orig_dev" && -n "$SAS" ]] && "$SAS" -s "$orig_dev" -t output >/dev/null
  fi
}
trap restore EXIT

osascript -e "set volume output muted false" -e "set volume output volume $VOL"
actual=$(osascript -e 'output volume of (get volume settings)')
cur_dev=$([[ -n "$SAS" ]] && "$SAS" -c -t output || echo "(unknown - install SwitchAudioSource)")

echo "output device: $cur_dev"
echo "output volume: $orig -> $actual   (muted was: $muted)"
echo "playing: $FILE"
if [[ "$KEEP" -eq 1 ]]; then
  echo "(keeping volume/device on exit)"
else
  echo "(will restore volume to $orig${orig_dev:+ and device to '$orig_dev'} on exit)"
fi

afplay "$FILE"
echo "done."
