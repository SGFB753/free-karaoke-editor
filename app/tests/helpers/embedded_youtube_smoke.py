"""Native WebView2 API smoke; optional --youtube checks the real reserve path.

Never reads Chrome/Edge profiles or stored user accounts. Run separately from
headless CI because this exercises the native GUI loop.
"""
import os
import sys
import tempfile
import threading
import json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import webview
from kstudio import embedded_youtube as E

fixture = """<div id="movie_player"></div><video></video><script>
document.getElementById('movie_player').getVideoData = () => ({video_id:'abcdefghijk'});
Object.defineProperty(document.querySelector('video'), 'readyState', {value:4});
</script>"""
result = {'ok': False}
main = webview.create_window('Studio reserve smoke', html='<p>Private smoke test</p>', hidden=True)


def check():
    child = None
    try:
        if '--youtube' in sys.argv:
            E.WAIT_SECONDS = 25
            with tempfile.TemporaryDirectory(prefix='karaoke-native-youtube-check-') as root:
                got = E.download('https://www.youtube.com/watch?v=wMV9EgCDcSI', root, print)
                result.update(ok=True, audio=os.path.getsize(got['path']) > 0)
        else:
            child = webview.create_window('Private child', html=fixture, hidden=True, js_api=None)
            if not child.events.loaded.wait(20):
                raise RuntimeError('Native child did not load')
            state = child.evaluate_js(E.PLAYER_STATE)
            result.update(ok=bool(state['ready'] and state['id']=='abcdefghijk'),
                          cookies_api=isinstance(child.get_cookies(), list))
    except Exception as exc:
        result.update(error=str(exc))
    finally:
        if child:
            child.destroy()
        E.close()
        main.destroy()


with tempfile.TemporaryDirectory(prefix='karaoke-private-webview-') as profile:
    # A timer also protects the smoke check against a wedged native API call.
    def stop():
        E.close()
        main.destroy()
    timer = threading.Timer(55, stop)
    timer.daemon = True
    timer.start()
    webview.start(check, gui='edgechromium', private_mode=True, storage_path=profile)
    timer.cancel()
print(json.dumps(result))
sys.exit(0 if result['ok'] else 1)
