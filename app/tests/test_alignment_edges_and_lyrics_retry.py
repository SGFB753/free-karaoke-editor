"""Silence-edge and transient lyrics-server regressions, without downloads."""
import io
import os
import sys
import unittest
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kstudio import align as A, lyrics as L, qwen as Q, findlyrics as FL


class EdgeTests(unittest.TestCase):
    def phrase(self):
        lyr = L.parse('Say hello again')
        for word, start, end in zip(lyr.words, [1, 17.2, 18], [17.2, 18, 22]):
            word.start, word.end = start, end
        lyr.lines[0].start, lyr.lines[0].end = 1, 22
        return lyr

    def envelope(self):
        env = [.5] * 1500  # 30 seconds
        env[50:835] = [0] * 785  # first word falsely covers a long interlude
        env[810] = .025  # isolated stem leakage is not the vocal onset
        env[1010:1150] = [0] * 140  # falsely held final word
        return env, .02

    def test_long_interlude_and_brief_leak(self):
        lyr = self.phrase()
        later = [(w.start, w.end) for w in lyr.words[1:]]
        with patch('kstudio.audio.rms_envelope', return_value=self.envelope()):
            self.assertEqual(A.refine_leading_silence(lyr, 'vocals', max_shift=30), 1)
            self.assertAlmostEqual(lyr.words[0].start, 16.64)
            self.assertEqual([(w.start, w.end) for w in lyr.words[1:]], later)
            self.assertEqual(A.refine_trailing_silence(lyr, 'vocals'), 1)
            self.assertAlmostEqual(lyr.words[-1].end, 20.26)

    def test_held_voice_and_protected_lines_unchanged(self):
        for protection in ('held', 'lock', 'keep', 'backing', 'anchor'):
            lyr = self.phrase()
            original = [(w.start, w.end) for w in lyr.words]
            if protection == 'anchor':
                lyr.fixed_line_indices = {0}
            elif protection != 'held':
                setattr(lyr.lines[0], protection, True)
            env = ([.5] * 1500, .02) if protection == 'held' else self.envelope()
            with patch('kstudio.audio.rms_envelope', return_value=env):
                A.refine_leading_silence(lyr, 'vocals', max_shift=30)
                A.refine_trailing_silence(lyr, 'vocals')
            self.assertEqual([(w.start, w.end) for w in lyr.words], original, protection)

    def test_silence_covering_complete_words_is_not_blindly_redistributed(self):
        lyr = self.phrase()
        lyr.words[0].end = 2
        original = [(w.start, w.end) for w in lyr.words]
        with patch('kstudio.audio.rms_envelope', return_value=self.envelope()):
            self.assertEqual(A.refine_leading_silence(lyr, 'vocals', max_shift=30), 0)
        self.assertEqual([(w.start, w.end) for w in lyr.words], original)

    def test_qwen_uses_edge_repairs_only_on_isolated_vocals(self):
        import numpy as np
        for isolated in (False, True):
            model = SimpleNamespace(align=lambda **kwargs: [[
                SimpleNamespace(text=text, start_time=start, end_time=end)
                for text, start, end in [('Say', 1, 17.2), ('hello', 17.2, 18), ('again', 18, 22)]]])
            with patch('kstudio.audio.read_pcm_mono', return_value=np.zeros(480000, dtype=np.int16)), \
                    patch('kstudio.audio.rms_envelope', return_value=self.envelope()):
                lyr = Q.align_qwen(L.parse('Say hello again'), 'vocals', 30, 'en',
                                   model=model, isolated=isolated)
            self.assertAlmostEqual(lyr.words[0].start, 16.64 if isolated else 1)
            self.assertAlmostEqual(lyr.words[-1].end, 20.26 if isolated else 22)


class RetryTests(unittest.TestCase):
    def error(self, code, headers=None):
        return HTTPError('https://lrclib.net', code, 'unavailable', headers or {}, None)

    def test_two_503_then_success(self):
        with patch.object(FL.urllib.request, 'urlopen', side_effect=[
                self.error(503), self.error(503), io.BytesIO(b'[]')]) as request, \
                patch.object(FL.time, 'sleep') as sleep:
            self.assertEqual(FL._ask('/api/search', {'q': 'song'}), [])
        self.assertEqual(request.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    def test_bounded_failure_and_nonretryable_status(self):
        for code, attempts in [(503, 3), (400, 1), (401, 1)]:
            with patch.object(FL.urllib.request, 'urlopen', side_effect=self.error(code)) as request, \
                    patch.object(FL.time, 'sleep') as sleep:
                with self.assertRaises(FL.LyricsError):
                    FL._ask('/api/search', {})
            self.assertEqual(request.call_count, attempts)
            self.assertEqual(sleep.call_count, attempts - 1)

    def test_retry_after_is_bounded_and_bad_headers_ignored(self):
        for value, expected in [('4', 4), ('999', 5), ('garbage', 1), ('nan', 1)]:
            with patch.object(FL.urllib.request, 'urlopen', side_effect=[
                    self.error(503, {'Retry-After': value}), io.BytesIO(b'[]')]), \
                    patch.object(FL.time, 'sleep') as sleep:
                FL._ask('/api/search', {})
            self.assertEqual(sleep.call_args.args[0], expected)

    def test_network_errors_retry_but_not_found_does_not(self):
        with patch.object(FL.urllib.request, 'urlopen', side_effect=[
                URLError('temporary'), io.BytesIO(b'[]')]), patch.object(FL.time, 'sleep') as sleep:
            self.assertEqual(FL._ask('/api/search', {}), [])
            sleep.assert_called_once_with(1)
        with patch.object(FL.urllib.request, 'urlopen', side_effect=self.error(404)) as request, \
                patch.object(FL.time, 'sleep') as sleep:
            self.assertEqual(FL._ask('/api/search', {}), [])
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main()
