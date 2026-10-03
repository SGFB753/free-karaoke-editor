"""Isolated, anonymous YouTube audio downloader used after yt-dlp refusal."""
import json
import os
import sys
from . import winproc


def main(args):
    # Guard runs Node through redirected subprocesses; hide those on Windows.
    winproc.install_frozen_policy()
    try:
        from pytubefix import YouTube
        from pytubefix.botGuard import bot_guard
        from .fetch import youtube_video_url, clean_title, split_name
        url, folder, limit = args
        limit = int(limit) * 1024 * 1024
        # Limit the token subprocess independently of the parent's wall clock.
        def token(video_id):
            return winproc.run([bot_guard.NODE_PATH, bot_guard.VM_PATH, video_id],
                              capture_output=True, check=True, timeout=30).stdout.decode().strip()
        bot_guard.generate_po_token = token

        def progress(stream, chunk, remaining):
            if stream.filesize - remaining > limit:
                raise ValueError('Audio exceeds the download size limit')

        video = YouTube(youtube_video_url(url), client='WEB',
                        use_oauth=False, allow_oauth_cache=False,
                        on_progress_callback=progress)
        stream = video.streams.filter(only_audio=True).order_by('abr').desc().first()
        if stream is None:
            raise ValueError('YouTube did not provide an audio stream')
        if stream.filesize > limit:
            raise ValueError('Audio exceeds the download size limit')
        path = stream.download(output_path=folder, filename='youtube.' + stream.subtype,
                               skip_existing=False, timeout=30, max_retries=0)
        if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise ValueError('YouTube returned no audio')
        artist, track = split_name(video.title)
        with open(os.path.join(folder, 'result.json'), 'w', encoding='utf-8') as f:
            json.dump(dict(name=os.path.basename(path), title=clean_title(video.title),
                           artist=artist, track=track, duration=video.length), f)
        return 0
    except Exception as exc:
        try:
            print(f'YouTube alternative: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        except Exception:
            pass
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
