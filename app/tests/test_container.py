#!/usr/bin/env python3
"""Karaoke in a container: it builds, it starts, and it makes a song.

Долгая проверка (сборка образа), поэтому по умолчанию она пропускается.
Включить:  KARAOKE_DOCKER=1 python3 tests/test_container.py
В общий прогон попадает при той же переменной.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

failures = []
IMAGE = "karaoke-studio:test"


def check(name, cond, extra=""):
    print(("  OK     " if cond else "  FAILED ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        failures.append(name)


def docker(*args, **kw):
    return subprocess.run(["docker", *args], capture_output=True, text=True, **kw)


def free_port(start=8901):
    import socket
    for port in range(start, start + 40):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def main():
    if not os.environ.get("KARAOKE_DOCKER"):
        print("  skipped: KARAOKE_DOCKER is not set (this check is slow)")
        return 0
    if shutil.which("docker") is None:
        print("  skipped: docker is not installed")
        return 0

    print("Building the image")
    r = docker("build", "-t", IMAGE, ROOT)
    check("the image was built", r.returncode == 0, (r.stderr or r.stdout).strip()[-300:])
    if r.returncode != 0:
        return 1

    tmp = tempfile.mkdtemp(prefix="karaoke_docker_")
    songs = os.path.join(tmp, "songs")
    music = os.path.join(tmp, "music")
    os.makedirs(songs, exist_ok=True)
    os.makedirs(music, exist_ok=True)
    from test_pipeline import TEXT, make_song
    make_song(os.path.join(music, "test.wav"))
    open(os.path.join(music, "test.txt"), "w", encoding="utf-8").write(TEXT)

    port = free_port()
    name = "karaoke-selftest"
    docker("rm", "-f", name)
    r = docker("run", "-d", "--name", name,
               "-p", f"127.0.0.1:{port}:8770",
               "-v", f"{songs}:/songs", "-v", f"{music}:/music:ro", IMAGE)
    check("the container started", r.returncode == 0, (r.stderr or "").strip()[-200:])
    if r.returncode != 0:
        return 1

    api = f"http://127.0.0.1:{port}"
    up = False
    for _ in range(60):
        try:
            urllib.request.urlopen(api + "/api/state", timeout=1)
            up = True
            break
        except Exception:
            time.sleep(0.5)
    check("the window answers from outside the container", up)

    try:
        if up:
            page = urllib.request.urlopen(api + "/").read().decode()
            check("it really is the studio", "Karaoke Studio" in page or "Караоке-студия" in page)
            caps = json.load(urllib.request.urlopen(api + "/api/state"))["caps"]
            check("ffmpeg is inside", caps["ffmpeg"])
            check("stable-ts is inside", caps["whisper"])
            check("demucs is inside", caps["demucs"])

            body = json.dumps({"audio": "/music/test.wav", "lyrics": "/music/test.txt",
                               "align": "energy", "separate": False}).encode()
            job = json.load(urllib.request.urlopen(urllib.request.Request(
                api + "/api/new", data=body, headers={"Content-Type": "application/json"})))
            st = {}
            for _ in range(300):
                st = json.load(urllib.request.urlopen(api + "/api/job?id=" + job["job"]))
                if st["done"]:
                    break
                time.sleep(0.5)
            check("a song was built inside the container", st.get("ok"), st.get("error"))
            made = os.listdir(songs)
            check("the project landed in the mounted folder, not in the image", bool(made),
                  ", ".join(made))
            check("the folder name is in Latin letters",
                  all(all(ord(c) < 128 for c in n) for n in made), ", ".join(made))
    finally:
        docker("rm", "-f", name)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("FAILED: " + ", ".join(failures) if failures else "All checks passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
