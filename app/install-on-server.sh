#!/usr/bin/env bash
# Installing karaoke on a clean virtual machine (Ubuntu/Debian/Fedora).
#
#   bash install-on-server.sh            # the CPU variant
#   bash install-on-server.sh --gpu      # if there is an NVIDIA card
#   bash install-on-server.sh --light    # no instrumental, easy on disk space
#   bash install-on-server.sh --models   # download the models in advance too
#
# The script can be run again — it does not break what is already installed.

set -u
GPU=0; LIGHT=0; MODELS=0
for a in "$@"; do
  case "$a" in
    --gpu)    GPU=1 ;;
    --light)  LIGHT=1 ;;
    --models) MODELS=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $a"; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"
step()  { echo; echo "=== $* ==="; }
die()   { echo; echo "STOP: $*" >&2; exit 1; }

# ---------------------------------------------------------------- 1. the system
step "1/5. System packages"

if   command -v apt-get >/dev/null; then PKG=apt
elif command -v dnf     >/dev/null; then PKG=dnf
else die "found neither apt nor dnf — install ffmpeg and python3 by hand"; fi

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

if [ "$PKG" = apt ]; then
  $SUDO apt-get update -qq || die "apt-get update failed"
  $SUDO apt-get install -y -qq ffmpeg python3 python3-pip python3-venv \
        fonts-dejavu-core || die "the system packages did not install"
else
  $SUDO dnf install -y -q ffmpeg python3 python3-pip dejavu-sans-fonts \
        || die "the system packages did not install"
fi

command -v ffmpeg >/dev/null || die "ffmpeg still is not there"
echo "  ffmpeg: $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f3)"
echo "  python: $(python3 -V 2>&1 | cut -d' ' -f2)"

python3 - <<'PY' || die "Python 3.8 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 8) else 1)
PY

# ---------------------------------------------------------------- 2. memory
step "2/5. Checking the memory"
python3 - <<'PY'
import re
try:
    info = open("/proc/meminfo").read()
    total = int(re.search(r"MemTotal:\s+(\d+)", info).group(1)) / 1048576
    swap  = int(re.search(r"SwapTotal:\s+(\d+)", info).group(1)) / 1048576
    print(f"  RAM: {total:.1f} GB, swap: {swap:.1f} GB")
    if total + swap < 6:
        print("  WARNING: less than 6 GB in total. The instrumental (~4 GB) may not fit.")
        print("  Either give the VM more memory or create a swap file:")
        print("    sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile")
        print("    sudo mkswap /swapfile && sudo swapon /swapfile")
    elif total + swap < 10:
        print("  Enough for small and for the instrumental. large-v3 needs more.")
    else:
        print("  Enough memory for any mode.")
except Exception as e:
    print("  could not tell:", e)
PY

# ---------------------------------------------------------------- 3. environment
step "3/5. A separate Python environment"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV" || die "the environment was not created (install python3-venv)"
  echo "  created: $VENV"
else
  echo "  already there: $VENV"
fi
# shellcheck disable=SC1091
. "$VENV/bin/activate"
pip install --quiet --upgrade pip

# ---------------------------------------------------------------- 4. libraries
step "4/5. Libraries"
echo "  This is the longest part: 1-2 GB is downloaded."

if [ "$GPU" -eq 1 ]; then
  echo "  Mode: NVIDIA card"
else
  echo "  Mode: CPU (torch without CUDA — four times lighter)"
  pip install --quiet torch==2.8.0 torchaudio==2.8.0 \
      --index-url https://download.pytorch.org/whl/cpu \
      || die "torch did not install"
fi

if [ "$LIGHT" -eq 1 ]; then
  echo "  Frugal mode: no instrumental"
else
  # soundfile is required: torchaudio 2.x cannot write WAV on its own, and
  # without it Demucs finishes the separation and then fails on writing it
  pip install --quiet "demucs==4.1.0" "soundfile==0.13.1" \
      || echo "  Demucs did not install — there will be no instrumental"
fi

pip install --quiet "stable-ts==2.19.1" || die "stable-ts did not install"
pip install --quiet "pillow==11.3.0"    || echo "  Pillow did not install — no video can be built"

# ---------------------------------------------------------------- 5. models
if [ "$MODELS" -eq 1 ]; then
  step "Downloading the models in advance"
  echo "  So there is no waiting later, on the first song."
  if [ "$LIGHT" -eq 0 ] && python3 -c "import demucs" 2>/dev/null; then
    echo "  Demucs (~80 MB)…"
    python3 -c "from demucs.pretrained import get_model; get_model('htdemucs'); print('    done')" \
      || echo "    it did not download — check the internet and try again"
  fi
  echo "  Whisper small (~480 MB)…"
  python3 -c "import whisper; whisper.load_model('small'); print('    done')" \
    || echo "    it did not download — check the internet and try again"
fi

# ---------------------------------------------------------------- 6. the check
step "Check"
ok=1
check() {
  if python3 -c "$2" >/dev/null 2>&1; then echo "  yes       $1"
  else echo "  NO        $1"; [ "$3" = req ] && ok=0; fi
}
check "timing (stable-ts)"        "import stable_whisper" req
check "instrumental (demucs)"     "import demucs"         opt
check "writing audio (soundfile)" "import soundfile"      opt
check "video (pillow)"            "from PIL import Image" opt
check "graphics card"             "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" opt

echo
python3 "$HERE/tests/test_pipeline.py" 2>&1 | tail -3
[ "$ok" -eq 1 ] || die "something important is missing, see above"

cat <<EOF

===============================================================
  Done. From here:

  source "$VENV/bin/activate"
  python3 karaoke.py "song.mp3" "lyrics.txt" -o "karaoke.html"

  Video:    python3 tools/video.py "karaoke.html"
  In bulk:  python3 tools/auto.py /folder/with/songs

  The first run takes longer: the Whisper model is downloaded (~480 MB for small).
===============================================================
EOF
