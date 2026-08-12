# Moving to another computer or a server

Everything needed to bring the processing up on a stronger machine.

Every version below has been checked: the whole chain was built and run
end to end — the instrumental, the Whisper timing and the page.

---

## Hardware

| What | Minimum | Sensible |
|---|---|---|
| RAM | 6 GB | **16 GB** |
| Disk | 8 GB | 15 GB |
| CPU | 4 cores | 8 cores |
| Graphics card | not needed | NVIDIA — 5–10 times faster |

Memory is the main thing. A shortage of it is what breaks the processing.
Step by step:

| Step | Peak memory |
|---|---|
| Instrumental (Demucs htdemucs) | ~4 GB |
| Whisper `tiny` | ~1.0 GB |
| Whisper `base` | ~1.3 GB |
| Whisper `small` | ~2.2 GB |
| Whisper `medium` | ~4.5 GB |
| Whisper `large-v3` | ~8.0 GB |

The steps run one after another, so what you need is the larger of the two, not
the sum. On 16 GB `large-v3` runs comfortably together with the instrumental.

Disk: the models are downloaded once and stay in the cache — Whisper up to 3 GB
(`~/.cache/whisper`), Demucs about 80 MB (`~/.cache/torch`).

---

## System packages

**ffmpeg** is required. Checked on 7.0.2; anything not older than 4.4 will do.

```bash
sudo apt update && sudo apt install -y ffmpeg python3 python3-pip python3-venv
```

For Fedora/RHEL — `sudo dnf install ffmpeg python3 python3-pip`.

A font with Cyrillic — needed only for rendering the video:

```bash
sudo apt install -y fonts-dejavu-core
```

---

## Python and the libraries

**Python 3.9 and newer.** Checked on 3.9.21.

```bash
python3 -m venv ~/karaoke-venv
source ~/karaoke-venv/bin/activate
pip install --upgrade pip
```

The set of versions that works:

```
stable-ts==2.19.1        checked
openai-whisper==20250625 checked
torch==2.8.0             checked
torchaudio==2.8.0        checked
numpy==2.0.2             checked
numba==0.60.0            checked
pillow==11.3.0           checked
demucs==4.1.0            checked
soundfile==0.13.1        checked, REQUIRED for the instrumental
```

**About soundfile.** Without it the instrumental breaks in a non-obvious way:
Demucs honestly finishes the separation and then fails while writing the result,
with `Couldn't find appropriate backend`. The reason is that torchaudio from
version 2.x on cannot write WAV itself, and Demucs does not pull that dependency
in. Checked: without soundfile there is no instrumental, with it there is.

In one command:

```bash
pip install "demucs==4.1.0" "soundfile==0.13.1" "stable-ts==2.19.1" "pillow==11.3.0"
```

The order is not accidental: Demucs is the pickiest about the torch version, so
let it choose first.

The rest comes in as dependencies. Without a graphics card you can install the
CPU build of torch — it is four times lighter:

```bash
pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cpu
```

With an NVIDIA card install the ordinary torch and add `--device cuda`.

---

## What to copy over

The program folder is enough — it is self-contained:

```
karaoke/
  karaoke.py          building from the command line
  studio.py           the window
  kstudio/            the engine
  tools/              video, diagnostics, editing a single line
```

The projects (`karaoke/projects/`) need not be copied — they are recreated.

---

## Running without the window

The main way on a server:

```bash
python3 app/karaoke.py "song.mp3" "lyrics.txt" -o "karaoke.html" \
    --align whisper --whisper-model medium
```

Options that come in handy:

| Option | What for |
|---|---|
| `--whisper-model large-v3` | the best accuracy, needs ~8 GB |
| `--device cuda` | compute on the graphics card |
| `--no-separate` | no instrumental, twice as fast and light |
| `--timings t.json` | take ready timings, skip Whisper |

The video the same way:

```bash
python3 app/tools/video.py "karaoke.html" -o "clip.mp4"
```

A whole folder in one go:

```bash
python3 tools/auto.py /path/to/the/folder
```

The files must be named alike: `Wind.mp3` + `Wind.txt`.

---

## The studio on a remote machine

The studio listens on `127.0.0.1` only — deliberately, so that it cannot be
opened from outside. The right way to reach it from your laptop is an SSH
tunnel:

```bash
ssh -L 8770:127.0.0.1:8770 user@server
```

In the same session, on the server:

```bash
python3 app/studio.py
```

Then open `http://127.0.0.1:8770/` on your own computer. The traffic goes inside
SSH, nothing sticks out.

Do not open the studio port to the network directly: it has neither passwords
nor access control, and it can read files and start processing.

---

## Checking that it all landed

```bash
python3 tests/test_pipeline.py
```

It must end with the line “All checks passed”. No neural nets are involved —
what is checked is the pipeline itself and ffmpeg.

Separately, to make sure the heavy libraries are alive:

```bash
python3 -c "import stable_whisper, torch; print('timing ok:', torch.__version__)"
python3 -c "import demucs, soundfile; print('instrumental ok')"
python3 -c "import torch; print('graphics card:', torch.cuda.is_available())"
python3 -c "from PIL import Image; print('video ok')"
```

Each line checks its own piece: if the second one fails there will be no
instrumental, if the fourth one does no video will be built. The rest keeps
working.

---

## If something does not download

The models are pulled from the network on the first run: Whisper from 75 MB to
3 GB depending on the one chosen, Demucs about 80 MB.

The program tells the reasons apart and says them in plain words, not in codes:

| What you see | What to do |
|---|---|
| “could not download the Whisper model” | check the internet, try again |
| “could not download the Demucs model” | the same; without it the build goes on with no instrumental |
| “the model file was damaged while downloading” | delete the cache and try again |
| “no package for writing audio” | `pip install soundfile` |

To download the models in advance and not wait later:

```bash
bash install-on-server.sh --models
```

The model cache lives in `~/.cache/whisper` and `~/.cache/torch/hub/checkpoints`.
It can be copied to another machine so nothing is downloaded twice.

---

## How long it takes

Rough numbers for a 3.5-minute song:

| Machine | Instrumental | Timing with `small` | Total |
|---|---|---|---|
| 4 cores, no graphics card | ~4 min | ~1 min | ~5 min |
| 8 cores, no graphics card | ~2 min | ~40 s | ~3 min |
| With NVIDIA | ~20 s | ~15 s | under a minute |

With `--no-separate` the time is roughly halved.
