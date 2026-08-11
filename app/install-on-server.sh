#!/usr/bin/env bash
# Установка караоке на чистую виртуальную машину (Ubuntu/Debian/Fedora).
#
#   bash install-on-server.sh            # процессорный вариант
#   bash install-on-server.sh --gpu      # если есть видеокарта NVIDIA
#   bash install-on-server.sh --light    # без минусовки, экономно по месту
#   bash install-on-server.sh --models   # заодно скачать модели заранее
#
# Скрипт можно запускать повторно — он не ломает уже установленное.

set -u
GPU=0; LIGHT=0; MODELS=0
for a in "$@"; do
  case "$a" in
    --gpu)    GPU=1 ;;
    --light)  LIGHT=1 ;;
    --models) MODELS=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Не понял ключ: $a"; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"
step()  { echo; echo "=== $* ==="; }
die()   { echo; echo "ОСТАНОВ: $*" >&2; exit 1; }

# ---------------------------------------------------------------- 1. система
step "1/5. Системные пакеты"

if   command -v apt-get >/dev/null; then PKG=apt
elif command -v dnf     >/dev/null; then PKG=dnf
else die "не нашёл ни apt, ни dnf — поставьте ffmpeg и python3 вручную"; fi

SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"

if [ "$PKG" = apt ]; then
  $SUDO apt-get update -qq || die "apt-get update не прошёл"
  $SUDO apt-get install -y -qq ffmpeg python3 python3-pip python3-venv \
        fonts-dejavu-core || die "не поставились системные пакеты"
else
  $SUDO dnf install -y -q ffmpeg python3 python3-pip dejavu-sans-fonts \
        || die "не поставились системные пакеты"
fi

command -v ffmpeg >/dev/null || die "ffmpeg так и не появился"
echo "  ffmpeg: $(ffmpeg -version 2>/dev/null | head -1 | cut -d' ' -f3)"
echo "  python: $(python3 -V 2>&1 | cut -d' ' -f2)"

python3 - <<'PY' || die "нужен Python 3.8 или новее"
import sys
raise SystemExit(0 if sys.version_info >= (3, 8) else 1)
PY

# ---------------------------------------------------------------- 2. память
step "2/5. Проверка памяти"
python3 - <<'PY'
import re
try:
    info = open("/proc/meminfo").read()
    total = int(re.search(r"MemTotal:\s+(\d+)", info).group(1)) / 1048576
    swap  = int(re.search(r"SwapTotal:\s+(\d+)", info).group(1)) / 1048576
    print(f"  оперативной памяти: {total:.1f} ГБ, подкачки: {swap:.1f} ГБ")
    if total + swap < 6:
        print("  ВНИМАНИЕ: меньше 6 ГБ суммарно. Минусовка (~4 ГБ) может не влезть.")
        print("  Либо добавьте памяти виртуалке, либо создайте файл подкачки:")
        print("    sudo fallocate -l 8G /swapfile && sudo chmod 600 /swapfile")
        print("    sudo mkswap /swapfile && sudo swapon /swapfile")
    elif total + swap < 10:
        print("  Хватит на small и минусовку. Для large-v3 нужно больше.")
    else:
        print("  Памяти достаточно на любой режим.")
except Exception as e:
    print("  не смог определить:", e)
PY

# ---------------------------------------------------------------- 3. окружение
step "3/5. Отдельное окружение Python"
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV" || die "не создалось окружение (поставьте python3-venv)"
  echo "  создано: $VENV"
else
  echo "  уже есть: $VENV"
fi
# shellcheck disable=SC1091
. "$VENV/bin/activate"
pip install --quiet --upgrade pip

# ---------------------------------------------------------------- 4. библиотеки
step "4/5. Библиотеки"
echo "  Это самая долгая часть: качается 1-2 ГБ."

if [ "$GPU" -eq 1 ]; then
  echo "  Режим: видеокарта NVIDIA"
else
  echo "  Режим: процессор (torch без CUDA — вчетверо легче)"
  pip install --quiet torch==2.8.0 torchaudio==2.8.0 \
      --index-url https://download.pytorch.org/whl/cpu \
      || die "не поставился torch"
fi

if [ "$LIGHT" -eq 1 ]; then
  echo "  Режим экономии: без минусовки"
else
  # soundfile обязателен: torchaudio 2.x не умеет писать WAV сам,
  # без него Demucs досчитает разделение и упадёт на записи результата
  pip install --quiet "demucs==4.1.0" "soundfile==0.13.1" \
      || echo "  Demucs не встал — минусовки не будет"
fi

pip install --quiet "stable-ts==2.19.1" || die "не поставился stable-ts"
pip install --quiet "pillow==11.3.0"    || echo "  Pillow не встал — видео собрать не выйдет"

# ---------------------------------------------------------------- 5. модели
if [ "$MODELS" -eq 1 ]; then
  step "Скачиваю модели заранее"
  echo "  Чтобы не ждать их потом, при первой песне."
  if [ "$LIGHT" -eq 0 ] && python3 -c "import demucs" 2>/dev/null; then
    echo "  Demucs (~80 МБ)…"
    python3 -c "from demucs.pretrained import get_model; get_model('htdemucs'); print('    готово')" \
      || echo "    не скачалась — проверьте интернет, потом повторите"
  fi
  echo "  Whisper small (~480 МБ)…"
  python3 -c "import whisper; whisper.load_model('small'); print('    готово')" \
    || echo "    не скачалась — проверьте интернет, потом повторите"
fi

# ---------------------------------------------------------------- 6. проверка
step "Проверка"
ok=1
check() {
  if python3 -c "$2" >/dev/null 2>&1; then echo "  есть      $1"
  else echo "  НЕТ       $1"; [ "$3" = req ] && ok=0; fi
}
check "разметка (stable-ts)" "import stable_whisper" req
check "минусовка (demucs)"   "import demucs"         opt
check "запись звука (soundfile)" "import soundfile"  opt
check "видео (pillow)"       "from PIL import Image" opt
check "видеокарта"           "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" opt

echo
python3 "$HERE/tests/test_pipeline.py" 2>&1 | tail -3
[ "$ok" -eq 1 ] || die "чего-то важного не хватает, смотрите выше"

cat <<EOF

===============================================================
  Готово. Дальше так:

  source "$VENV/bin/activate"
  python3 karaoke.py "песня.mp3" "текст.txt" -o "караоке.html"

  Видео:   python3 tools/video.py "караоке.html"
  Пачкой:  python3 tools/auto.py /папка/с/песнями

  Первый запуск дольше: качается модель Whisper (~480 МБ для small).
===============================================================
EOF
