"""Browser-invisible copied marks must not turn into glyphs in video/cover art."""
import copy
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kstudio import lyrics as L
from tools import video as V
from PIL import Image, ImageFont


class VideoTextTests(unittest.TestCase):
    clean = 'Ты говоришь: «Спасибо»'
    dirty = 'Ты говоришь: «\u200eСпасибо\u200e»'

    def line(self, text):
        return dict(text=text, start=2, end=5, section='Куплет', voice=1,
                    words=[dict(w=w, t=2 + i, d=1, s=1) for i, w in enumerate(text.split())])

    def test_import_removes_directional_marks_without_changing_manual_time(self):
        lyrics = L.parse('title: \u200eSong\u200e\nartist: \u200fArtist\u200f\n[00:02.00]' + self.dirty)
        self.assertEqual((lyrics.title, lyrics.artist), ('Song', 'Artist'))
        self.assertEqual(lyrics.lines[0].text, self.clean)
        self.assertEqual(lyrics.lines[0].start, 2)
        self.assertEqual([w.text for w in lyrics.words], self.clean.split())

    def test_real_arrows_joiners_and_emoji_are_preserved(self):
        text = '→ ↱ می\u200cروم 👩\u200d🎤 ❤️'
        self.assertEqual(L.clean_display_text('\ufeff\u061c\u202a' + text + '\u202c\u2066\u2069'), text)

    def test_old_project_renders_like_clean_text_and_keeps_all_word_timing(self):
        line = self.line(self.dirty)
        before = copy.deepcopy(line)
        measured = []
        def font_for(text, max_w, main):
            measured.append(text)
            size = 40
            font = ImageFont.truetype(V.find_font(), size)
            while size > 14 and font.getlength(text) > max_w:
                size -= 2
                font = ImageFont.truetype(V.find_font(), size)
            return font
        dirty = V.LineArt(line, font_for, 1000, 40)
        clean = V.LineArt(self.line(self.clean), font_for, 1000, 40)
        self.assertEqual(dirty.dim.tobytes(), clean.dim.tobytes())
        self.assertEqual(dirty.hot.tobytes(), clean.hot.tobytes())
        self.assertEqual(dirty.word_x, clean.word_x)
        self.assertEqual(dirty.word_w, clean.word_w)
        self.assertTrue(all('\u200e' not in text for text in measured))
        self.assertEqual(line, before)
        for t in (1, 2, 2.5, 3.5, 5):
            self.assertEqual(dirty.hot_boxes(line, t), clean.hot_boxes(self.line(self.clean), t))

    def test_unsegmented_text_and_countdown_use_clean_text(self):
        font = lambda *args: ImageFont.truetype(V.find_font(), 40)
        dirty = V.LineArt(dict(text=self.dirty, words=[]), font, 1000, 40)
        clean = V.LineArt(dict(text=self.clean, words=[]), font, 1000, 40)
        self.assertEqual(dirty.dim.tobytes(), clean.dim.tobytes())
        self.assertEqual(V.short_line(self.dirty, most=200), self.clean)

    def test_cover_and_title_card_do_not_draw_control_marks(self):
        dirty = {'data': dict(title='\u200eSong\u200e', artist='\u200fArtist\u200f')}
        clean = {'data': dict(title='Song', artist='Artist')}
        self.assertEqual(V.title_card_image(dirty, 640, 360).tobytes(),
                         V.title_card_image(clean, 640, 360).tobytes())

    def test_exported_frame_matches_clean_lyrics_including_name_and_section(self):
        with tempfile.TemporaryDirectory() as folder:
            audio = str(Path(folder) / 'audio.wav')
            with wave.open(audio, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
                wav.writeframes(b'\0\0' * 8000 * 8)
            frames = []
            for dirty in (True, False):
                line = self.line(self.dirty if dirty else self.clean)
                if dirty:
                    line['section'] = '\u200eКуплет\u200e'
                data = dict(title='\u200eSong\u200e' if dirty else 'Song',
                            artist='\u200fArtist\u200f' if dirty else 'Artist',
                            duration=8, lines=[line])
                out = str(Path(folder) / ('dirty.png' if dirty else 'clean.png'))
                args = SimpleNamespace(width=640, height=360, fps=30, crf=30,
                    preset='ultrafast', font=None, intro=False, card=False,
                    start=0, seconds=0, audio='minus', timings=None, output=out, still=2.5)
                V.render({'data': data}, audio, out, args)
                with Image.open(out) as image:
                    frames.append(image.tobytes())
            self.assertEqual(frames[0], frames[1])


if __name__ == '__main__':
    unittest.main()
