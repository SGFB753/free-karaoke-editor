"""Changing imported project visuals must preserve audio, timing and old assets on failure."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Item
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import studio as S
from kstudio import project as P, jobcontrol as JC


class BackdropTests(unittest.TestCase):
    def test_link_video_downloader_uses_the_bundled_javascript_runtime(self):
        calls=[]
        def attempt(args,log,deadline):
            calls.append(args)
            Path(args[args.index('-o')+1].replace('%(ext)s','webm')).write_bytes(b'video')
            return 0,[]
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(S.FE,'tool',return_value=['yt-dlp']), \
                patch.object(S.FE,'javascript_args',return_value=['--js-runtimes','node:C:/node.exe']), \
                patch.object(S.FE,'extra_args',return_value=[]), \
                patch.object(S.FE,'_attempt',side_effect=attempt):
            output=S.FE.clip('https://youtu.be/abcdefghijk',folder)
            self.assertTrue(Path(output).is_file())
        self.assertIn('--js-runtimes',calls[0])
        self.assertIn('node:C:/node.exe',calls[0])

    def test_export_names_follow_edited_credits_and_keep_cyrillic(self):
        data = dict(title='Песня',artist='Первый, Второй',source_title='wrong video name')
        self.assertEqual(P.export_stem(data),'Первый, Второй - Песня')
        self.assertEqual(P.export_stem(dict(data,title='Новая песня')),'Первый, Второй - Новая песня')
        self.assertEqual(P.export_stem(dict(data,artist='')),'Песня')
        self.assertEqual(P.export_stem({'source_title':'Legacy video'}),'Legacy video')
        self.assertNotIn('/',P.export_stem(dict(data,title='Песня/часть?')))

    def test_failed_conversion_keeps_existing_video_and_cleans_temporary_output(self):
        with tempfile.TemporaryDirectory() as folder:
            dst=Path(folder)/'backdrop.mp4'
            dst.write_bytes(b'previous video')
            with patch.object(S.AU,'ffmpeg',return_value='ffmpeg'), \
                    patch('subprocess.run',return_value=Item(returncode=1,stderr=b'bad clip')):
                with self.assertRaises(ValueError): S.set_backdrop(folder,'bad-input')
            self.assertEqual(dst.read_bytes(),b'previous video')
            self.assertEqual(os.listdir(folder),['backdrop.mp4'])

    def test_link_download_is_staged_and_survives_cleanup_and_reopening(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as staging:
            original=dict(duration=3,title='Track',artist='Artist',lines=[],tracks={'mix':'mix.mp3'})
            P.save(folder,original)
            downloaded=[]
            def download(url,work,log):
                path=Path(work)/'backdrop.mp4'
                path.write_bytes(b'large source')
                downloaded.append(path)
                return str(path)
            def convert(command,**kwargs):
                Path(command[-1]).write_bytes(b'reduced video')
                return Item(returncode=0,stderr=b'')
            with patch.object(S,'staging_dir',return_value=staging), \
                    patch.object(S.FE,'clip',side_effect=download), \
                    patch.object(S.AU,'ffmpeg',return_value='ffmpeg'), \
                    patch('subprocess.run',side_effect=convert):
                result=S.set_backdrop_url(folder,'https://example.com/clip',lambda s:None)
            self.assertTrue(result['backdrop'])
            self.assertFalse(downloaded[0].exists())
            self.assertEqual((Path(folder)/'backdrop.mp4').read_bytes(),b'reduced video')
            data=P.load(folder)
            self.assertEqual(data['backdropUrl'],'https://example.com/clip')
            self.assertEqual(data['tracks'],original['tracks'])
            self.assertEqual(data['lines'],original['lines'])

    def test_cancellation_before_commit_preserves_old_video(self):
        with tempfile.TemporaryDirectory() as folder:
            dst=Path(folder)/'backdrop.mp4'
            dst.write_bytes(b'old')
            control=JC.Control()
            def convert(command,**kwargs):
                Path(command[-1]).write_bytes(b'new')
                control.cancel()
                return Item(returncode=0,stderr=b'')
            with patch.object(S.AU,'ffmpeg',return_value='ffmpeg'), \
                    patch('subprocess.run',side_effect=convert):
                with self.assertRaises(JC.Cancelled), JC.scope(control):
                    S.set_backdrop(folder,'input')
            self.assertEqual(dst.read_bytes(),b'old')
            self.assertEqual(os.listdir(folder),['backdrop.mp4'])

    def test_video_and_cover_share_the_project_credit_stem(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            data=dict(duration=1,title='Песня',artist='Артист',source_title='wrong source',lines=[],tracks={})
            P.save(folder,data)
            video=Item(extract_audio=lambda *a:'audio.wav',render=lambda *a,**k:None,
                       title_card_image=lambda *a:Image.new('RGB',(2,2)))
            with patch.object(S,'ready_dir',return_value=folder), \
                    patch.object(S,'_video_module',return_value=video), \
                    patch.object(S,'_lyrics_from',return_value=Item()), \
                    patch.object(S.B,'build_html'), patch.object(S.B,'read_payload',return_value={}):
                result=S.export(folder,'mp4',{'cover':True},lambda s:None)
            self.assertEqual(os.path.basename(result['path']),'Артист - Песня.mp4')
            self.assertEqual(os.path.basename(result['cover']),'Артист - Песня.jpg')
            self.assertTrue(os.path.isfile(result['cover']))


if __name__=='__main__': unittest.main()
