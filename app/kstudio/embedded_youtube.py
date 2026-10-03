"""Last-resort YouTube session in Studio's private native browser.

No access to installed browser profiles, no remote Python API, and no account
session written into project/settings files. Reuse the window during this app
session to avoid asking the same verification question for every download.
"""
import os
import tempfile
import threading
import time
from http.cookiejar import Cookie, MozillaCookieJar
from urllib.parse import urlsplit, parse_qs
from . import fetch as F
from .i18n import tr

_lock = threading.Lock()
_window = None
_closed = None
WAIT_SECONDS = 180

# Read the actual player's state, not merely the presence of a YouTube page.
# Do not click consent dialogs, log into accounts, or solve challenges for users.
PLAYER_STATE = """(() => {
 const p = document.getElementById('movie_player');
 const data = p && p.getVideoData ? p.getVideoData() : null;
 const video = document.querySelector('video');
 if (video) { video.muted = true;
   if (video.paused) video.play().catch(() => {}); }
 return {id: data && data.video_id,
   ready: !!(video && video.readyState >= 2 && p && !video.error),
   ua: navigator.userAgent};
})()"""


def cookie_jar(cookies):
    """Copy only this embedded session's YouTube cookies, including HttpOnly."""
    jar = MozillaCookieJar()
    for group in cookies:
        for morsel in group.values():
            domain = morsel['domain'].lower()
            host = domain.lstrip('.')
            if host != 'youtube.com' and not host.endswith('.youtube.com'):
                continue
            jar.set_cookie(Cookie(0, morsel.key, morsel.value, None, False,
                domain, True, domain.startswith('.'), morsel['path'] or '/', True,
                bool(morsel['secure']), None, True, None, None,
                {'HttpOnly': None} if morsel['httponly'] else {}))
    return jar


def close():
    global _window
    window, _window = _window, None
    if window is not None:
        try:
            window.destroy()
        except Exception:
            pass


def download(url, dest_dir, log=None):
    """Open only after other downloaders failed; resume without a Retry button."""
    global _window, _closed
    say = log or (lambda _: None)
    url = F.youtube_video_url(url)
    video_id = parse_qs(urlsplit(url).query)['v'][0]
    if not _lock.acquire(blocking=False):
        raise F.FetchError(tr('Another YouTube verification is already open.',
                              'Уже выполняется другая проверка YouTube.'))
    window = None
    try:
        import webview
        say(tr('Trying Studio’s private YouTube session. No installed-browser cookies are used.',
               'Пробую собственную приватную сессию YouTube. Cookies установленных браузеров не используются.'))
        if _window is None or _closed.is_set():
            _closed = threading.Event()
            _window = webview.create_window(
                tr('YouTube verification — Karaoke Studio', 'Проверка YouTube — Караоке-студия'),
                url=url, width=960, height=720, min_size=(640, 480), hidden=True,
                js_api=None, background_color='#0b0c14', text_select=True)
            _window.events.closed += _closed.set
        else:
            _window.load_url(url)
        window = _window
        closed = _closed
        start = time.monotonic()
        shown = False
        state = None
        while time.monotonic() - start < WAIT_SECONDS:
            if closed.wait(.5):
                raise F.FetchError(tr('YouTube verification window was closed. Download stopped.',
                                      'Окно проверки YouTube закрыто. Загрузка остановлена.'))
            if window.events.loaded.is_set():
                current = window.get_current_url() or ''
                if F.youtube_url(current):
                    try:
                        state = window.evaluate_js(PLAYER_STATE)
                    except Exception:
                        state = None
                    if isinstance(state, dict) and state.get('id') == video_id and state.get('ready'):
                        break
            if not shown and time.monotonic() - start >= 8:
                window.show()
                shown = True
                say(tr('Complete YouTube’s consent/check in the opened window. Download resumes automatically. Close the window to stop. Account login is optional and may carry download-account risks.',
                       'Если YouTube просит согласие или проверку, пройдите её в открытом окне. Загрузка продолжится сама. Закрытие окна остановит попытку. Вход в аккаунт необязателен; использование аккаунта для загрузок связано с риском ограничений.'))
        else:
            raise F.FetchError(tr('YouTube verification timed out. Try another connection or a local file.',
                                  'Время проверки YouTube истекло. Попробуйте другое подключение или локальный файл.'))
        # Query only after being back on YouTube, never on a Google login page.
        jar = cookie_jar(window.get_cookies())
        window.evaluate_js("document.querySelector('video')?.pause()")
        window.hide()
        say(tr('YouTube player is ready — downloading automatically…',
               'Проигрыватель YouTube готов — продолжаю загрузку автоматически…'))
        os.makedirs(dest_dir, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.youtube-session-', dir=dest_dir) as tmp:
            cookies = os.path.join(tmp, 'session.txt')
            jar.save(cookies, ignore_discard=True, ignore_expires=True)
            if os.name != 'nt':
                os.chmod(cookies, 0o600)
            # yt-dlp prints its cookie-file path only, never cookie values.
            return F._download(url, dest_dir, say, cookie_file=cookies, user_agent=state.get('ua'))
    except F.FetchError:
        raise
    except Exception as exc:
        # Third-party errors must not dump session contents into job logs.
        raise F.FetchError(tr('Studio’s YouTube session could not be used.',
                              'Не удалось использовать собственную сессию YouTube в студии.')) from exc
    finally:
        if window is not None:
            try:
                window.hide()
            except Exception:
                pass
        _lock.release()
