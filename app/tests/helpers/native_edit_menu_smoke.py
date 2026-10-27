"""Exercise native right-click events without accessing the OS clipboard.

Uses an off-screen WebView2 with its own private profile. The test observer
suppresses each popup after recording the production handler's decision.
"""
import ctypes
from ctypes import wintypes
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import webview
from kstudio import edit_menu as E

result = {'ok': False}
window = webview.create_window(
    'Studio native editing smoke', hidden=True, focus=False,
    html='''<style>input,textarea{position:absolute;left:20px;width:300px;height:30px}
    </style><input style="top:20px" value="Song title">
    <input type="url" style="top:70px" value="https://example.com">
    <textarea style="top:120px">Lyrics</textarea>''',
    text_select=True, width=500, height=300)
E.install(window)


def check():
    try:
        if not window.events.loaded.wait(20):
            raise RuntimeError('WebView2 did not load')
        from System import Action
        from System.Drawing import Point
        observed = threading.Event()

        def observe(_sender, args):
            result.setdefault('requests', []).append({
                'editable': bool(args.ContextMenuTarget.IsEditable),
                'handled': bool(args.Handled),
                'commands': [item.Name for item in args.MenuItems],
            })
            args.Handled = True
            observed.set()

        def prepare():
            core = window.native.webview.CoreWebView2
            core.ContextMenuRequested += observe
            result['native_menu'] = bool(core.Settings.AreDefaultContextMenusEnabled)
            result['devtools'] = bool(core.Settings.AreDevToolsEnabled)
            window.native.Location = Point(-10000, -10000)
            window.native.Show()

        window.native.webview.Invoke(Action(prepare))
        user = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user.EnumChildWindows.argtypes = (wintypes.HWND, callback_type, wintypes.LPARAM)
        user.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
        user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        children = []

        @callback_type
        def visit(handle, _):
            name = ctypes.create_unicode_buffer(256)
            user.GetClassNameW(handle, name, len(name))
            if 'RenderWidgetHost' in name.value:
                children.append(handle)
            return True

        deadline = time.monotonic() + 5
        while not children and time.monotonic() < deadline:
            user.EnumChildWindows(int(window.native.Handle.ToInt64()), visit, 0)
            time.sleep(.05)
        target = children[0]
        user.GetDpiForWindow.argtypes = (wintypes.HWND,)
        scale = user.GetDpiForWindow(target) / 96
        time.sleep(.2)
        for y in (35, 85, 135, 195):
            observed.clear()
            point = (int(y * scale) << 16) | int(100 * scale)
            for message, buttons in ((0x0200, 0), (0x0204, 2), (0x0205, 0)):
                user.PostMessageW(target, message, buttons, point)
            if not observed.wait(5):
                raise RuntimeError(f'No native context menu at y={y}')
        requests = result['requests']
        result['ok'] = (result['native_menu'] and not result['devtools']
                        and all(r['editable'] and not r['handled']
                                and {'cut', 'copy', 'paste'} <= set(r['commands'])
                                and len(r['commands']) == 4
                                and set(r['commands'][:3]) == {'cut', 'copy', 'paste'}
                                for r in requests[:3])
                        and not requests[3]['editable'] and requests[3]['handled'])
    except Exception as exc:
        result.update(ok=False, error=str(exc))
    finally:
        window.destroy()


with tempfile.TemporaryDirectory(prefix='karaoke-edit-menu-smoke-') as profile:
    timer = threading.Timer(45, window.destroy)
    timer.daemon = True
    timer.start()
    webview.start(check, gui='edgechromium', private_mode=True, storage_path=profile)
    timer.cancel()
print(json.dumps(result))
sys.exit(0 if result['ok'] else 1)
