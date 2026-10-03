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


if __name__=='__main__': unittest.main()
