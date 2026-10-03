"""Reserve routing, private cookie scope, window lifecycle; no real accounts."""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kstudio import fetch as F
from kstudio import embedded_youtube as E

URL = 'https://www.youtube.com/watch?v=abcdefghijk'


def cookie(domain, value='secret'):
    c = SimpleCookie()
    c['session'] = value
    c['session']['domain'] = domain
    c['session']['path'] = '/'
    c['session']['secure'] = True
    c['session']['httponly'] = True
    return c


class EmbeddedTests(unittest.TestCase):
    def tearDown(self):
        E._window = None
        E._closed = None

    def test_only_youtube_cookies_are_exported(self):
        jar = E.cookie_jar([cookie('.youtube.com'), cookie('accounts.google.com'),
                            cookie('youtube.com.evil'), cookie('www.youtube.com')])
        self.assertEqual({c.domain for c in jar}, {'.youtube.com', 'www.youtube.com'})
        self.assertTrue(all(c.secure and c.has_nonstandard_attr('HttpOnly') for c in jar))

    def test_last_resort_only_and_no_browser_profile_read(self):
        embedded = Mock(return_value={'path':'audio'})
        with patch.object(F, '_download_sources', return_value={'path':'ordinary'}):
            self.assertEqual(F.download(URL, 'unused', embedded=embedded)['path'], 'ordinary')
            embedded.assert_not_called()
        with patch.object(F, '_download_sources', side_effect=F.BrowserRequired('not a bot')), \
                patch.object(F, 'extra_args', return_value=[]):
            self.assertEqual(F.download(URL, 'unused', embedded=embedded)['path'], 'audio')
        embedded.assert_called_once_with(URL, 'unused', None)

    def test_refused_authorised_browser_also_reaches_native_reserve(self):
        for message in ('Failed to decrypt with DPAPI', 'Sign in to confirm you are not a bot'):
            embedded = Mock(return_value={'path':'native audio'})
            with patch.object(F, '_download_sources', side_effect=F.FetchError(message)), \
                    patch.object(F, 'extra_args', return_value=[]):
                self.assertEqual(F.download(URL,'unused',browser='edge',embedded=embedded)['path'], 'native audio')
            embedded.assert_called_once()

    def test_skip_private_network_other_sites_and_explicit_settings(self):
        for url, error, extra in ((URL,F.FetchError('private video'),[]),
                (URL,F.FetchError('connection reset'),[]),
                ('https://example.org/watch',F.BrowserRequired('not a bot'),[]),
                (URL,F.BrowserRequired('not a bot'),['--proxy','custom'])):
            embedded = Mock()
            with patch.object(F,'_download_sources',side_effect=error), \
                    patch.object(F,'extra_args',return_value=extra):
                with self.assertRaises(F.FetchError): F.download(url,'unused',embedded=embedded)
                embedded.assert_not_called()

    def window(self):
        window = Mock()
        window.events = SimpleNamespace(loaded=threading.Event(), closed=EventHandlers())
        window.events.loaded.set()
        window.get_current_url.return_value = URL
        window.evaluate_js.return_value = {'id':'abcdefghijk','ready':True,'ua':'WebView test'}
        window.get_cookies.return_value = [cookie('.youtube.com'), cookie('.example.com')]
        return window

    def test_automatic_resume_private_cookie_file_deleted_and_reuse(self):
        window = self.window()
        fake = SimpleNamespace(create_window=Mock(return_value=window))
        captured = []
        def download(url, root, log, **kw):
            path = kw['cookie_file']
            captured.append(path)
            with open(path) as f: data = f.read()
            self.assertIn('secret',data)
            self.assertNotIn('example.com',data)
            self.assertEqual(kw['user_agent'],'WebView test')
            self.assertNotIn('browser', kw)
            return {'path':'audio'}
        with tempfile.TemporaryDirectory() as root, patch.dict(sys.modules,webview=fake), \
                patch.object(F,'_download',side_effect=download):
            self.assertEqual(E.download(URL,root)['path'],'audio')
            self.assertFalse(os.path.exists(captured[0]))
            self.assertEqual(E.download(URL,root)['path'],'audio')
            self.assertEqual(os.listdir(root),[])
        fake.create_window.assert_called_once()
        self.assertIsNone(fake.create_window.call_args.kwargs['js_api'])
        self.assertTrue(fake.create_window.call_args.kwargs['hidden'])
        window.show.assert_not_called()
        window.load_url.assert_called_once_with(URL)

    def test_cookie_file_deleted_even_on_download_failure(self):
        window = self.window()
        fake = SimpleNamespace(create_window=Mock(return_value=window))
        with tempfile.TemporaryDirectory() as root, patch.dict(sys.modules,webview=fake), \
                patch.object(F,'_download',side_effect=F.FetchError('refused')):
            with self.assertRaises(F.FetchError): E.download(URL,root)
            self.assertEqual(os.listdir(root),[])

    def test_closed_window_stops_without_downloading(self):
        window = self.window()
        def create(*args, **kw):
            E._closed.set()
            return window
        with patch.dict(sys.modules,webview=SimpleNamespace(create_window=create)), \
                patch.object(F,'_download') as download:
            with self.assertRaisesRegex(F.FetchError,'closed|закрыто'): E.download(URL,'unused')
            download.assert_not_called()

    def test_lock_prevents_multiple_verification_windows(self):
        E._lock.acquire()
        try:
            with self.assertRaises(F.FetchError): E.download(URL,'unused')
        finally:
            E._lock.release()

    def test_manual_check_shows_window_and_then_resumes_without_retry_click(self):
        window = self.window()
        window.evaluate_js.side_effect = [
            {'id':'abcdefghijk','ready':False},
            {'id':'abcdefghijk','ready':True,'ua':'test'}, None]
        fake = SimpleNamespace(create_window=Mock(return_value=window))
        with tempfile.TemporaryDirectory() as root, patch.dict(sys.modules,webview=fake), \
                patch.object(E.time,'monotonic',side_effect=[0,1,9,10]), \
                patch.object(F,'_download',return_value={'path':'audio'}) as downloader:
            self.assertEqual(E.download(URL,root)['path'],'audio')
        window.show.assert_called_once()
        downloader.assert_called_once()

    def test_timeout_stops_and_wrong_video_does_not_download(self):
        window = self.window()
        window.evaluate_js.return_value={'id':'different-id','ready':True}
        fake=SimpleNamespace(create_window=Mock(return_value=window))
        with patch.dict(sys.modules,webview=fake), \
                patch.object(E.time,'monotonic',side_effect=[0,1,9,181]), \
                patch.object(F,'_download') as downloader:
            with self.assertRaises(F.FetchError): E.download(URL,'unused')
        downloader.assert_not_called()


class EventHandlers:
    def __iadd__(self, handler):
        return self


if __name__ == '__main__':
    unittest.main()
