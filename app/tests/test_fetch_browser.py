"""Browser cookies must never be read without consent or on unrelated failures."""
import os
import sys
import tempfile
import unittest
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kstudio import fetch as F


class BrowserFallbackTests(unittest.TestCase):
    def setUp(self):
        self.real_alternative = F._independent_download
        alternative = patch.object(F, '_independent_download', side_effect=F.FetchError('alternative refused'))
        self.alternative = alternative.start()
        self.addCleanup(alternative.stop)

    def test_alternative_is_automatic_before_any_browser(self):
        self.alternative.side_effect = None
        self.alternative.return_value = {'path': 'audio'}
        with patch.object(F, '_download', side_effect=F.BrowserRequired('not a bot')), patch.object(F, 'extra_args', return_value=[]):
            self.assertEqual(F.download('https://youtu.be/abcdefghijk', 'unused'), {'path': 'audio'})
        self.alternative.assert_called_once()

    def test_alternative_child_result_and_cleanup(self):
        def child(command, **options):
            import subprocess
            folder = command[-2]
            with open(os.path.join(folder, 'youtube.m4a'), 'wb') as f:
                f.write(b'audio')
            with open(os.path.join(folder, 'result.json'), 'w') as f:
                json.dump({'name':'youtube.m4a','title':'Song','artist':'Singer',
                           'track':'Song','duration':10}, f)
            self.assertLessEqual(options['timeout'], 180)
            self.assertNotIn('--cookies', command)
            return subprocess.CompletedProcess(command, 0, '', '')
        with tempfile.TemporaryDirectory() as root, patch.object(F.WP,'run',side_effect=child):
            result = self.real_alternative('https://youtu.be/abcdefghijk',root)
            self.assertTrue(os.path.isfile(result['path']))
            self.assertEqual(os.listdir(root), ['youtube.m4a'])

    def test_alternative_timeout_cleans_up(self):
        import subprocess
        with tempfile.TemporaryDirectory() as root, patch.object(F.WP,'run',
                side_effect=subprocess.TimeoutExpired('download',180)):
            with self.assertRaises(F.FetchError):
                self.real_alternative('https://youtu.be/abcdefghijk',root)
            self.assertEqual(os.listdir(root), [])

    def test_local_permission_api_rejects_foreign_pages(self):
        import studio as S
        with tempfile.TemporaryDirectory() as root, patch.object(S,'PROJECTS',root):
            server=ThreadingHTTPServer(('127.0.0.1',0),S.Handler)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            url=f'http://127.0.0.1:{server.server_port}/api/fetch/browser'
            body=json.dumps({'browser':'edge'}).encode()
            try:
                for headers in ({'Content-Type':'text/plain'},
                                {'Content-Type':'application/json','Origin':'https://foreign.example'}):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(url,data=body,headers=headers))
                    self.assertEqual(error.exception.code,403)
                    self.assertEqual(os.listdir(root),[])
                with urlopen(Request(url,data=body,headers={'Content-Type':'application/json'})) as r:
                    self.assertEqual(json.load(r),{'browser':'edge'})
                self.assertEqual(F.saved_browser(os.path.join(root,'.download-browser.json')),'edge')
            finally:
                server.shutdown();server.server_close()

    def test_consent_saves_only_browser_and_can_be_revoked(self):
        with tempfile.TemporaryDirectory() as root:
            path=os.path.join(root,'preference.json')
            self.assertIsNone(F.saved_browser(path))
            F.save_browser(path,'firefox')
            self.assertEqual(F.saved_browser(path),'firefox')
            with open(path) as f: self.assertEqual(f.read(),'{"browser": "firefox"}')
            F.save_browser(path,None)
            self.assertIsNone(F.saved_browser(path))
            with self.assertRaises(F.FetchError): F.save_browser(path,'chrome --cookies hacked')

    def test_external_url_strips_tracking_and_accepts_youtube_url_variants(self):
        for source in ('https://youtu.be/abcdefghijk?pp=tracking',
                       'https://www.youtube.com/watch?v=abcdefghijk&list=private',
                       'https://youtube.com/shorts/abcdefghijk',
                       'https://m.youtube.com/live/abcdefghijk'):
            self.assertEqual(F.youtube_video_url(source),'https://www.youtube.com/watch?v=abcdefghijk')
        for source in ('file:///private.txt','https://youtube.com.evil/watch?v=abcdefghijk',
                       'https://youtube.com/playlist?list=abc','https://user:secret@youtube.com/watch?v=abcdefghijk'):
            with self.assertRaises(F.FetchError): F.youtube_video_url(source)

    def test_authorised_browser_is_one_explicit_fallback(self):
        with patch.object(F,'_download',side_effect=[F.BrowserRequired('not a bot'),{'path':'audio'}]) as work, \
                patch.object(F,'extra_args',return_value=[]):
            result=F.download('https://youtu.be/video','unused',browser='edge')
            self.assertEqual(result,{'path':'audio'})
            self.assertEqual(work.call_count,2)
            self.assertEqual(work.call_args.kwargs,{'browser':'edge'})

    def test_no_consent_no_cookies(self):
        with patch.object(F,'_download',side_effect=F.BrowserRequired('not a bot')) as work:
            with self.assertRaises(F.BrowserRequired): F.download('https://youtu.be/video','unused')
            self.assertEqual(work.call_count,1)

    def test_permission_click_skips_the_already_refused_anonymous_attempt(self):
        with patch.object(F,'_download',return_value={'path':'audio'}) as work, \
                patch.object(F,'extra_args',return_value=[]):
            F.download('https://youtu.be/video','unused',browser='edge',browser_only=True)
            self.assertEqual(work.call_count,1)
            self.assertEqual(work.call_args.kwargs,{'browser':'edge'})
        with patch.object(F,'_download') as work:
            with self.assertRaises(F.FetchError):
                F.download('https://youtu.be/video','unused',browser_only=True)
            work.assert_not_called()

    def test_ordinary_success_never_reads_cookies(self):
        with patch.object(F,'_download',return_value={'path':'audio'}) as work:
            F.download('https://youtu.be/video','unused',browser='edge')
            self.assertEqual(work.call_count,1)
            self.assertEqual(work.call_args.kwargs,{})

    def test_private_network_unrelated_and_custom_cookie_failures_are_not_retried(self):
        for url,error,extra in (
                ('https://youtu.be/video',F.FetchError('private video'),[]),
                ('https://youtu.be/video',F.FetchError('connection reset'),[]),
                ('https://example.com/video',F.BrowserRequired('429'),[]),
                ('https://youtu.be/video',F.BrowserRequired('not a bot'),['--cookies','user.txt'])):
            with patch.object(F,'_download',side_effect=error) as work, patch.object(F,'extra_args',return_value=extra):
                with self.assertRaises(F.FetchError): F.download(url,'unused',browser='chrome')
                self.assertEqual(work.call_count,1)

    def test_authenticated_refusal_stops_and_cleans_temp_files(self):
        with tempfile.TemporaryDirectory() as root, patch.object(F,'tool',return_value=['downloader']), \
                patch.object(F,'extra_args',return_value=[]), \
                patch.object(F,'_network_attempt',return_value=(1,['ERROR: Sign in to confirm you are not a bot'])) as attempt:
            with self.assertRaises(F.FetchError):
                F.download('https://youtube.com/watch?v=video',root,browser='firefox')
            self.assertEqual(attempt.call_count,2)
            anonymous,authenticated=[call.args[0] for call in attempt.call_args_list]
            self.assertNotIn('--cookies-from-browser',anonymous)
            self.assertEqual(authenticated[-4:],['--cookies-from-browser','firefox','--','https://youtube.com/watch?v=video'])
            self.assertEqual(os.listdir(root),[])


class RecoveryTests(unittest.TestCase):
    URL = 'https://youtu.be/j082huGdeag'

    def test_generic_unavailable_retries_the_same_command_once(self):
        import time
        command = ['downloader', '--', self.URL]
        log = []
        with patch.object(F, '_attempt', side_effect=[
                (1, ['ERROR: [youtube] j082huGdeag: This video is not available']),
                (0, ['done'])]) as attempt, patch.object(F.time, 'sleep') as sleep:
            self.assertEqual(F._network_attempt(command, log.append, time.time() + 60)[0], 0)
        self.assertEqual(attempt.call_count, 2)
        self.assertEqual(attempt.call_args_list[0].args, attempt.call_args_list[1].args)
        sleep.assert_called_once_with(2)
        self.assertTrue(any('2' in line for line in log))

    def test_permanent_refusals_and_limits_do_not_repeat(self):
        import time
        for message in (
                'Video unavailable. This video is private',
                'This video is not available: video has been deleted',
                'This video is not available due to a copyright claim',
                'This video is unavailable in your country',
                'The uploader has not made this video available in your country',
                'Video unavailable. HTTP Error 429',
                'Video unavailable. CERTIFICATE_VERIFY_FAILED'):
            with patch.object(F, '_attempt', return_value=(1, [message])) as attempt, \
                    patch.object(F.time, 'sleep') as sleep:
                F._network_attempt(['downloader', self.URL], lambda _: None, time.time() + 60)
            self.assertEqual(attempt.call_count, 1, message)
            sleep.assert_not_called()

    def test_unavailable_retry_is_bounded_and_respects_deadline(self):
        import time
        for remaining, expected in ((60, 2), (-1, 1)):
            with patch.object(F, '_attempt', return_value=(1, ['This video is not available'])) as attempt, \
                    patch.object(F.time, 'sleep'):
                F._network_attempt(['downloader', self.URL], lambda _: None, time.time() + remaining)
            self.assertEqual(attempt.call_count, expected)

    def test_generic_refusal_reaches_independent_then_private_reserve(self):
        from unittest.mock import Mock
        embedded = Mock(return_value={'path': 'reserve audio'})
        with patch.object(F, '_download', side_effect=F.FetchError('This video is not available')), \
                patch.object(F, 'extra_args', return_value=[]), \
                patch.object(F, '_independent_download', side_effect=F.FetchError('alternative refused')) as alternative:
            self.assertEqual(F.download(self.URL, 'unused', embedded=embedded)['path'], 'reserve audio')
        alternative.assert_called_once()
        embedded.assert_called_once()

    def test_independent_success_does_not_open_browser(self):
        from unittest.mock import Mock
        embedded = Mock()
        with patch.object(F, '_download', side_effect=F.FetchError('This video is not available')), \
                patch.object(F, 'extra_args', return_value=[]), \
                patch.object(F, '_independent_download', return_value={'path': 'audio'}) as alternative:
            self.assertEqual(F.download(self.URL, 'unused', embedded=embedded), {'path': 'audio'})
        alternative.assert_called_once()
        embedded.assert_not_called()

    def test_explicit_restriction_discovered_by_reserve_stops_further_attempts(self):
        from unittest.mock import Mock
        embedded = Mock()
        for reason in ('Video unavailable: private video', 'CERTIFICATE_VERIFY_FAILED'):
            with patch.object(F, '_download', side_effect=F.FetchError('This video is not available')), \
                    patch.object(F, 'extra_args', return_value=[]), \
                    patch.object(F, '_independent_download', side_effect=F.FetchError(reason)):
                with self.assertRaisesRegex(F.FetchError, reason):
                    F.download(self.URL, 'unused', embedded=embedded)
        embedded.assert_not_called()

    def test_restrictions_other_sites_and_explicit_options_do_not_trigger_reserve(self):
        from unittest.mock import Mock
        for url, message, extra in (
                (self.URL, 'Video unavailable: private video; unable to extract', []),
                (self.URL, 'Video unavailable: copyright; player response missing', []),
                (self.URL, 'Video unavailable: CERTIFICATE_VERIFY_FAILED', []),
                ('https://example.com/video', 'Video unavailable', []),
                (self.URL, 'This video is not available', ['--proxy', 'custom'])):
            embedded = Mock()
            with patch.object(F, '_download', side_effect=F.FetchError(message)), \
                    patch.object(F, 'extra_args', return_value=extra), \
                    patch.object(F, '_independent_download') as alternative:
                with self.assertRaises(F.FetchError):
                    F.download(url, 'unused', embedded=embedded)
            alternative.assert_not_called()
            embedded.assert_not_called()

    def test_runtime_uses_the_bundled_node_path_with_spaces(self):
        from types import SimpleNamespace
        folder = os.path.join('runtime with spaces', 'nodejs_wheel')
        module = SimpleNamespace(__file__=os.path.join(folder, '__init__.py'))
        with patch.dict(sys.modules, {'nodejs_wheel': module}), \
                patch.dict(os.environ, {'KARAOKE_YTDLP': ''}), \
                patch.object(F, '_setting', return_value=''), \
                patch.object(F, 'extra_args', return_value=[]), \
                patch.object(F.os.path, 'isfile', return_value=True):
            result = F.javascript_args()
        expected = os.path.join(folder, 'node.exe') if os.name == 'nt' else os.path.join(folder, 'bin', 'node')
        self.assertEqual(result, ['--js-runtimes', 'node:' + expected])

    def test_explicit_runtime_or_downloader_settings_win(self):
        for extra in (['--no-js-runtimes'], ['--js-runtimes', 'node:custom'], ['--js-runtimes=deno']):
            with patch.dict(os.environ, {'KARAOKE_YTDLP': ''}), \
                    patch.object(F, '_setting', return_value=''), patch.object(F, 'extra_args', return_value=extra):
                self.assertEqual(F.javascript_args(), [])
        with patch.dict(os.environ, {'KARAOKE_YTDLP': 'custom-downloader'}):
            self.assertEqual(F.javascript_args(), [])

    def test_managed_downloader_wins_over_unrelated_path_command(self):
        from types import SimpleNamespace
        for frozen in (False, True):
            with patch.dict(sys.modules, {'yt_dlp': SimpleNamespace()}), \
                    patch.dict(os.environ, {'KARAOKE_YTDLP': ''}), \
                    patch.object(F, '_setting', return_value=''), \
                    patch.object(sys, 'frozen', frozen, create=True), \
                    patch.object(F.shutil, 'which', return_value='unrelated-yt-dlp'):
                expected = [sys.executable, '--internal-ytdlp'] if frozen else [sys.executable, '-m', 'yt_dlp']
                self.assertEqual(F.tool(), expected)


class CachedNodeTests(unittest.TestCase):
    def test_cached_node_updates_pytubefix_runners_too(self):
        from types import ModuleType
        from pathlib import Path
        from kstudio import components as C
        package = ModuleType('nodejs_wheel'); package.__path__ = []
        package.__file__ = 'old-runtime/nodejs_wheel/__init__.py'
        executable = ModuleType('nodejs_wheel.executable'); executable.ROOT_DIR = 'old-runtime'
        package.executable = executable
        runner = ModuleType('pytubefix.sig_nsig.node_runner'); runner.NODE_DIR = 'old-runtime'
        guard = ModuleType('pytubefix.botGuard.bot_guard'); guard.NODE_DIR = 'old-runtime'; guard.NODE_PATH = 'old.exe'
        with patch.dict(sys.modules, {'nodejs_wheel': package, 'nodejs_wheel.executable': executable,
                'pytubefix.sig_nsig.node_runner': runner, 'pytubefix.botGuard.bot_guard': guard}), \
                patch.object(C, 'supported', return_value=True), patch.object(C, 'ensure', return_value=Path('cached-node')), \
                patch.object(F.os.path, 'isfile', return_value=False), patch.object(F, '_setting', return_value=''), \
                patch.object(F, 'extra_args', return_value=[]), patch.dict(os.environ, {'KARAOKE_YTDLP': ''}):
            result = F.javascript_args()
        self.assertEqual(result, ['--js-runtimes', 'node:' + str(Path('cached-node')/'node.exe')])
        self.assertEqual(executable.ROOT_DIR, 'cached-node')
        self.assertEqual(runner.NODE_DIR, 'cached-node')
        self.assertEqual(guard.NODE_PATH, str(Path('cached-node')/'node.exe'))


if __name__=='__main__': unittest.main()
