# Karaoke Studio in a container: nothing to install on the machine except Docker
# itself, and nothing from the internet runs outside the box.
#
#   docker build -t karaoke app
#   docker run --rm -p 8770:8770 -v "$PWD/projects:/songs" -v "$HOME/Music:/music:ro" karaoke
#
# Then open http://127.0.0.1:8770/ — the window is the same, only the program
# runs inside the container. Add --gpus all for an NVIDIA card (see README).
FROM python:3.11-slim

# ffmpeg is the only system dependency; git is what pip needs for some wheels.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The heavy wheels are installed first so that editing the code does not
# re-download PyTorch on every build.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app

# Songs live outside the container, in a mounted folder: a container is
# disposable, a person's work is not.
ENV KARAOKE_PROJECTS=/songs \
    KARAOKE_UI_LANG=auto \
    XDG_CACHE_HOME=/cache
VOLUME ["/songs", "/cache"]
EXPOSE 8770

# --host 0.0.0.0 is needed because the request comes from outside the container.
CMD ["python", "studio.py", "--port", "8770", "--no-browser", "--host", "0.0.0.0"]
