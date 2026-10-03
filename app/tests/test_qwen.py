"""Qwen integration contracts, without network downloads or neural weights."""
import os
import sys
import unittest
import tempfile
from types import SimpleNamespace as Item
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kstudio import align as A, lyrics as L, qwen as Q, report as R
from kstudio import models as M


class FakeModel:
    def __init__(self):
        self.calls = []

    def align(self, *, audio, text, language):
        self.calls.append((len(audio[0]) / audio[1], text, language))
        words = [Q._key(w) for w in text.split() if Q._key(w)]
        return [[Item(text=w, start_time=.2 + i * .4, end_time=.5 + i * .4)
                 for i, w in enumerate(words)]]


class QwenTests(unittest.TestCase):
    def test_compressed_multisyllable_word_requests_retry_not_redistribution(self):
        lyr=L.parse('Я приеду в Петербург')
        for word,a,b in zip(lyr.words,[12.16,12.48,12.57,12.64],[12.48,12.57,12.64,13.36]):
            word.start,word.end=a,b
        original=[(w.start,w.end) for w in lyr.words]
        self.assertGreater(Q._faults(lyr.lines)[0],0)
        self.assertEqual([(w.start,w.end) for w in lyr.words],original)
        lyr.words[1].end=12.62
        lyr.words[2].start=12.62
        lyr.words[2].end=12.70
        lyr.words[3].start=12.70
        self.assertEqual(Q._faults(lyr.lines),[0])
        lyr.words[-1].end=20
        self.assertEqual(Q._faults(lyr.lines),[0])
        lyr.words[1].end=12.80
        lyr.words[2].start=12.57
        self.assertGreater(Q._faults(lyr.lines)[0],0)
        lyr.words[2].start=lyr.words[2].end=12.64
        lyr.words[3].start=12.64
        lyr.words[1].end=12.64
        self.assertGreater(Q._faults(lyr.lines)[0],0)

    def test_mass_collapse_is_language_and_song_independent(self):
        for text in ('Hello again world', 'Снова здравствуй мир', 'Noch einmal willkommen'):
            lyr=L.parse('\n'.join([text]*8))
            for word in lyr.words:
                word.start=word.end=42
            self.assertTrue(Q._failed_placement(lyr.lines))
            for i,word in enumerate(lyr.words):
                word.start,word.end=i*.4,i*.4+.3
            self.assertFalse(Q._failed_placement(lyr.lines))
            lyr.words[-1].end+=20
            self.assertFalse(Q._failed_placement(lyr.lines))

    def test_short_phrase_retry_recovers_internal_word_split_without_touching_neighbour(self):
        import numpy as np
        lyr=L.parse('Я приеду в Петербург\nЗайму бабло')
        model=FakeModel()
        baseline=[(12.16,12.48),(12.48,12.57),(12.57,12.64),(12.64,13.36),
                  (13.36,14.08),(14.08,14.8)]
        def infer(**kwargs):
            text=kwargs['text']
            model.calls.append((len(kwargs['audio'][0])/16000,text))
            times=([(0.25,0.40),(0.40,0.90),(0.90,0.97),(0.97,1.45)]
                   if text=='Я приеду в Петербург' else baseline)
            return [[Item(text=w,start_time=a,end_time=b)
                     for w,(a,b) in zip(text.split(),times)]]
        model.align=infer
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(320000,dtype=np.int16)):
            Q.align_qwen(lyr,'unused',20,'ru',model=model)
        self.assertGreater(lyr.lines[0].words[1].end-lyr.lines[0].words[1].start,.4)
        self.assertEqual([(w.start,w.end) for w in lyr.lines[1].words],baseline[-2:])
        self.assertTrue(any(duration<2 and '\n' not in text for duration,text in model.calls))

    def test_mass_failure_uses_independent_bounds_not_failed_qwen_anchors(self):
        import numpy as np
        lyr=L.parse('\n'.join(['Hello again world']*8))
        model=FakeModel()
        def infer(**kwargs):
            words=kwargs['text'].split()
            if len(words)==24:
                return [[Item(text=w,start_time=10,end_time=10) for w in words]]
            return [[Item(text=w,start_time=.2+i*.4,end_time=.5+i*.4) for i,w in enumerate(words)]]
        model.align=infer
        windows=[(0,4,0,10),(4,8,10,20)]
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(320000,dtype=np.int16)), \
                patch.object(Q,'_independent_jobs',return_value=windows) as guide:
            Q.align_qwen(lyr,'vocals',20,'en',model=model,fallback_audio='original')
        self.assertEqual(guide.call_args.args[1],'original')
        self.assertFalse(Q._failed_placement(lyr.lines))
        self.assertGreater(lyr.lines[4].start,10)

    def test_mass_failure_is_never_hidden_by_minimum_word_lengths(self):
        import numpy as np
        lyr=L.parse('\n'.join(['Hello again world']*8))
        model=FakeModel()
        model.align=lambda **kw:[[Item(text=w,start_time=1,end_time=1) for w in kw['text'].split()]]
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(320000,dtype=np.int16)), \
                patch.object(Q,'_independent_jobs',return_value=[(0,4,0,10),(4,8,10,20)]), \
                patch.object(A,'_fill_lines') as fill:
            with self.assertRaisesRegex(ValueError,'will not be saved|не будет сохранён'):
                Q.align_qwen(lyr,'unused',20,'en',model=model)
            fill.assert_not_called()

    def test_energy_and_low_confidence_cannot_supply_recovery_anchors(self):
        lyr=L.parse('\n'.join(['Hello again world']*8))
        def guide(lyrics,*args,**kw):
            for i,ln in enumerate(lyrics.lines):
                for j,w in enumerate(ln.words):
                    w.start,w.end,w.prob=i*2+j*.4,i*2+j*.4+.3,0
                ln.start,ln.end=ln.words[0].start,ln.words[-1].end
        with patch.object(A,'align_whisper',side_effect=guide), \
                patch.object(A,'align_energy',side_effect=AssertionError('energy must not anchor Qwen')):
            with self.assertRaisesRegex(ValueError,'boundaries|границы'):
                Q._independent_jobs(lyr.lines,'audio',20,0,20,'en',None,lambda msg:None,[], 'small')

    def test_cache_status_requires_both_weights_and_tokenizer_files(self):
        with tempfile.TemporaryDirectory(prefix='karaoke_qwen_cache_') as folder, \
             patch.object(M,'qwen_dir',return_value=folder), patch.object(M,'_MIN_BYTES',2):
            files=('config.json','preprocessor_config.json','tokenizer_config.json',
                   'vocab.json','merges.txt','model.safetensors')
            for name in files:
                with open(os.path.join(folder,name),'wb') as f:
                    f.write(b'123')
            self.assertTrue(M.qwen_ready())
            os.remove(os.path.join(folder,'vocab.json'))
            self.assertFalse(M.qwen_ready())
    def test_punctuation_hyphens_and_original_spelling(self):
        words = [L.Word('Ёжик-то,'), L.Word('поёт!')]
        items = [Item(text='Ёжикто', start_time=.4, end_time=.8),
                 Item(text='поёт', start_time=1.1, end_time=1.3)]
        Q.assign_words(words, items, 0, lambda t: t + 10, 2)
        self.assertEqual([w.text for w in words], ['Ёжик-то,', 'поёт!'])
        self.assertEqual([(w.start, w.end) for w in words], [(10.4,10.8),(11.1,11.3)])
        self.assertTrue(all(w.prob is None for w in words))

    def test_split_tokens_are_recombined(self):
        word = L.Word('你好')
        Q.assign_words([word], [Item(text='你',start_time=.1,end_time=.3),
                                Item(text='好',start_time=.4,end_time=.7)], 0, lambda t:t, 1)
        self.assertEqual((word.start, word.end), (.1,.7))

    def test_wrapper_interpolation_is_flagged_before_absolute_offsets_are_added(self):
        words = [L.Word('Hello'), L.Word('world')]
        Q.assign_words(words, [Item(text='Hello',start_time=.24,end_time=.4),
                               Item(text='world',start_time=.488,end_time=.696)],
                       0, lambda t:t+6.45, 2, timestamp_step=.08)
        self.assertFalse(words[0].qwen_interpolated)
        self.assertTrue(words[1].qwen_interpolated)
        self.assertGreater(Q._faults([L.Line('Hello world',words=words)])[0],0)
        self.assertIsNone(words[1].prob)

    def test_bad_tokens_and_timestamps_fail_explicitly(self):
        for item in (Item(text='wrong',start_time=0,end_time=.2),
                     Item(text='word',start_time=float('nan'),end_time=.2),
                     Item(text='word',start_time=.5,end_time=.2),
                     Item(text='word',start_time=0,end_time=10)):
            with self.assertRaises(ValueError):
                Q.assign_words([L.Word('word')],[item],0,lambda t:t,1)

    def test_skip_offset_and_no_whisper_repairs(self):
        import numpy as np
        model = FakeModel()
        lyr = L.parse('Hello, world!')
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(160000,dtype=np.int16)), \
             patch.object(A,'repair_lines',side_effect=AssertionError('Whisper repair called')):
            Q.align_qwen(lyr,'unused',10,'en',skip=[(0,2),(5,10)],model=model)
        self.assertEqual(model.calls[0], (3.0,'Hello, world!','English'))
        self.assertEqual(lyr.words[0].start,2.2)
        self.assertTrue(all(2 <= w.start <= w.end <= 5 for w in lyr.words))

    def test_ready_line_timestamps_stay_fixed(self):
        import numpy as np
        model = FakeModel()
        lyr = L.parse('[00:02.00]Hello world\n[00:05.00]Good night')
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(160000,dtype=np.int16)):
            Q.align_qwen(lyr,'unused',10,'en',model=model)
        self.assertEqual([ln.start for ln in lyr.lines],[2,5])
        self.assertTrue(lyr.fixed_line_starts)
        self.assertEqual(lyr.fixed_line_indices,{0,1})

    def test_word_edges_on_a_stitched_boundary_use_opposite_sides_of_the_pause(self):
        import numpy as np
        model=FakeModel()
        model.align=lambda **kwargs:[[Item(text='Hello',start_time=.2,end_time=3),
                                      Item(text='world',start_time=3,end_time=3.5)]]
        lyr=L.parse('Hello world')
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(160000,dtype=np.int16)):
            Q.align_qwen(lyr,'unused',10,'en',skip=[(0,2),(5,7)],model=model)
        self.assertEqual(lyr.words[0].end,5)
        self.assertEqual(lyr.words[1].start,7)

    def test_long_song_with_short_kept_audio_needs_only_one_call(self):
        import numpy as np
        model=FakeModel()
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(6400000,dtype=np.int16)):
            Q.align_qwen(L.parse('Hello world'),'unused',400,'en',skip=[(0,200),(203,400)],model=model)
        self.assertEqual(len(model.calls),1)
        self.assertEqual(model.calls[0][0],3)

    def test_long_song_windows_are_bounded_and_cover_each_line_once(self):
        lines=L.parse('\n'.join('Hello world' for _ in range(60))).lines
        def coarse(lyrics,*args,**kwargs):
            for i,ln in enumerate(lyrics.lines):
                ln.start,ln.end = i*10,i*10+4
        with patch.object(A,'align_energy',side_effect=coarse):
            jobs=Q._jobs(lines,600,'unused',lambda msg:None)
        self.assertGreater(len(jobs),1)
        self.assertEqual([ln for group,_,_ in jobs for ln in group],lines)
        self.assertTrue(all(0 <= a < b <= 600 and b-a <= 300 for _,a,b in jobs))

    def test_no_audio_or_unsupported_language_is_not_silently_replaced(self):
        import numpy as np
        with self.assertRaisesRegex(ValueError,'Qwen'):
            Q.align_qwen(L.parse('Привіт'),'unused',10,'uk',model=FakeModel())
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(160000,dtype=np.int16)), \
             patch.object(A, 'align_whisper', side_effect=AssertionError('No audio must not trigger model recovery')):
            with self.assertRaises(ValueError):
                Q.align_qwen(L.parse('Hello'),'unused',10,'en',skip=[(0,10)],model=FakeModel())

    def test_missing_optional_whisper_recovery_has_a_readable_error(self):
        with patch.object(A, 'align_whisper', side_effect=ModuleNotFoundError('stable_whisper')):
            with self.assertRaisesRegex(ValueError, 'Whisper'):
                Q._independent_jobs(L.parse('Hello').lines, 'unused', 10, 0, 10,
                                    'en', None, lambda msg: None, [], 'small')

    def test_engine_dispatch_never_calls_whisper(self):
        lyr=L.parse('Hello')
        with patch.object(Q,'align_qwen',return_value=lyr) as run, \
             patch.object(A,'align_whisper',side_effect=AssertionError('Whisper used')):
            aligned,used=A.align(lyr,'unused',10,'qwen',language='en')
        self.assertIs(aligned,lyr)
        self.assertEqual(used,'qwen')
        run.assert_called_once()

    def test_report_names_qwen_and_warns_about_unsupported_language(self):
        rep=R.build('unused',L.parse('Привіт'),10,[],.02,language='uk',engine='qwen',separate=False)
        self.assertEqual(rep['plan']['engine'],'qwen')
        self.assertFalse(rep['plan']['whisper'])
        self.assertIn('Qwen',R.as_text(rep))
        self.assertTrue(any('Qwen' in n for n in rep['notes']))

    def test_stem_is_only_preferred_for_qwen(self):
        self.assertEqual(Q.timing_source('original', 'vocal', 'qwen'), ('vocal', True))
        for engine in ('auto', 'whisper', 'energy'):
            self.assertEqual(Q.timing_source('original', 'vocal', engine), ('original', False))
        self.assertEqual(Q.timing_source('original', None, 'qwen'), ('original', False))

    def test_retiming_respects_engine_override_and_missing_stems(self):
        import studio as ST
        with tempfile.TemporaryDirectory(prefix='karaoke_qwen_sources_') as folder:
            for name in ('original.wav', 'vocal.wav'):
                with open(os.path.join(folder, name), 'wb') as f:
                    f.write(b'audio')
            original, vocal = [os.path.join(folder, n) for n in ('original.wav', 'vocal.wav')]
            data = dict(engine='qwen', source_audio=original, tracks={'vocals': 'vocal.wav'})
            self.assertEqual(ST.timing_audio(folder, data), (vocal, True))
            self.assertEqual(ST.timing_audio(folder, data, 'auto'), (original, False))
            data['tracks']['vocals'] = 'missing.wav'
            self.assertEqual(ST.timing_audio(folder, data), (original, False))

    @staticmethod
    def phrase_fixture():
        lyr = L.parse('[Chorus]\nHello world\nGood night\n[Verse]\nI arrive home\nGood night')
        times = [(1, 1.3), (1.8, 2.1), (2.2, 2.4), (2.5, 2.9),
                 (3, 3), (10, 10.4), (10.4, 10.8), (11, 11.2), (11.4, 11.8)]
        for w, (a, b) in zip(lyr.words, times):
            w.start, w.end = a, b
        return lyr

    def test_quality_does_not_mistake_a_held_note_or_marked_pause_for_failure(self):
        lyr = L.parse('Hello world')
        lyr.words[0].start, lyr.words[0].end = 1, 9
        lyr.words[1].start, lyr.words[1].end = 15, 16
        self.assertGreater(Q._faults(lyr.lines)[0], 0)
        self.assertEqual(Q._faults(lyr.lines, [(9,15)]), [0])
        lyr.words[1].start = 9
        self.assertEqual(Q._faults(lyr.lines), [0])

    def test_retry_anchors_ignore_a_stray_word_before_the_interlude(self):
        lyr = self.phrase_fixture()
        self.assertEqual(Q._core_bounds(lyr.lines[2]), (10,10.8))
        jobs = Q._retry_jobs(lyr.lines, 0, 20)
        self.assertEqual(jobs, [(0,2,0,6.45), (2,4,6.45,20)])
        self.assertGreater(Q._faults(lyr.lines)[2], 0)

    def test_no_anchor_means_no_invented_proportional_cut(self):
        lyr = self.phrase_fixture()
        for w in lyr.words:
            w.start = w.end = 10
        self.assertEqual(Q._retry_jobs(lyr.lines,0,20), [(0,4,0,20)])

    def test_local_retry_fixes_the_bad_phrase_but_keeps_healthy_words_and_gaps(self):
        import numpy as np
        baseline = self.phrase_fixture()
        model = FakeModel()

        def infer(**kwargs):
            model.calls.append(kwargs['text'])
            if kwargs['text'].startswith('Hello'):
                return [[Item(text=w.text, start_time=w.start, end_time=w.end) for w in baseline.words]]
            # Window starts at 6.45: actual corrected phrase starts at 10.
            times = [(3.55,3.75), (3.75,4.15), (4.15,4.55), (5,5.5), (6,6.5)]
            return [[Item(text=w, start_time=a, end_time=b)
                     for w,(a,b) in zip(kwargs['text'].split(),times)]]

        model.align = infer
        lyr = L.parse('[Chorus]\nHello world\nGood night\n[Verse]\nI arrive home\nGood night')
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(320000,dtype=np.int16)):
            Q.align_qwen(lyr,'unused',20,'en',model=model)
        self.assertEqual(len(model.calls),2)
        for i in (0,1,3):
            self.assertEqual([(w.start,w.end) for w in lyr.lines[i].words],
                             [(w.start,w.end) for w in baseline.lines[i].words])
        self.assertAlmostEqual(lyr.lines[2].start,10)
        self.assertEqual(Q._faults(lyr.lines),[0,0,0,0])

    def test_a_worse_retry_cannot_replace_the_existing_phrase(self):
        import numpy as np
        baseline = self.phrase_fixture()
        model = FakeModel()
        calls = []

        def infer(**kwargs):
            calls.append(kwargs['text'])
            if kwargs['text'].startswith('Hello'):
                return [[Item(text=w.text,start_time=w.start,end_time=w.end) for w in baseline.words]]
            return [[Item(text=w,start_time=.5,end_time=.5) for w in kwargs['text'].split()]]

        model.align = infer
        logs = []
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(320000,dtype=np.int16)):
            Q.align_qwen(baseline,'unused',20,'en',model=model,log=logs.append)
        self.assertEqual(len(calls),2)
        self.assertEqual(baseline.lines[2].words[1].start,10)
        self.assertTrue(any('3' in msg and ('check phrase' in msg or 'проверьте привязку' in msg) for msg in logs))

    def test_unusable_stem_can_be_retried_on_original_without_switching_models(self):
        import numpy as np
        model = FakeModel()
        def infer(**kwargs):
            valid = float(kwargs['audio'][0][0]) > 0
            return [[Item(text='Hello',start_time=.2,end_time=.5 if valid else .2),
                     Item(text='world',start_time=.6,end_time=1 if valid else .6)]]
        model.align = infer
        with patch('kstudio.audio.read_pcm_mono',side_effect=[np.zeros(160000,dtype=np.int16),
                                                            np.ones(160000,dtype=np.int16)]) as decode:
            lyr = Q.align_qwen(L.parse('Hello world'),'stem',10,'en',model=model,fallback_audio='original')
        self.assertEqual(decode.call_args_list[0].args,('stem',16000))
        self.assertEqual(decode.call_args_list[0].kwargs,{})
        self.assertEqual(Q._faults(lyr.lines),[0])

    def test_an_unreadable_fallback_does_not_discard_the_primary_alignment(self):
        import numpy as np
        model = FakeModel()
        model.align = lambda **kwargs:[[Item(text='Hello',start_time=.2,end_time=.2),
                                       Item(text='world',start_time=.6,end_time=1)]]
        logs = []
        with patch('kstudio.audio.read_pcm_mono',side_effect=[np.zeros(160000,dtype=np.int16),
                                                            OSError('file disappeared')]):
            lyr = Q.align_qwen(L.parse('Hello world'),'stem',10,'en',model=model,
                               fallback_audio='original',log=logs.append)
        self.assertEqual(lyr.words[1].start,.6)
        self.assertTrue(any('file disappeared' in msg for msg in logs))

    def test_local_token_mismatch_is_rejected_not_spread_evenly(self):
        import numpy as np
        baseline = self.phrase_fixture()
        model = FakeModel()
        def infer(**kwargs):
            if kwargs['text'].startswith('Hello'):
                return [[Item(text=w.text,start_time=w.start,end_time=w.end) for w in baseline.words]]
            return [[Item(text='wrong',start_time=.5,end_time=1)]]
        model.align = infer
        with patch('kstudio.audio.read_pcm_mono',return_value=np.zeros(320000,dtype=np.int16)):
            Q.align_qwen(baseline,'unused',20,'en',model=model)
        self.assertEqual(baseline.lines[2].words[1].start,10)

    def test_same_voice_tail_stops_at_the_next_phrase_without_moving_onsets(self):
        lyr = L.parse('Whole phrase\nNext phrase')
        for word, times in zip(lyr.words, [(103.24,103.8),(103.8,105.16),
                                          (104.848,105.024),(105.2,106.4)]):
            word.start, word.end = times
        self.assertEqual(Q.trim_same_voice_tails(lyr),1)
        self.assertEqual(lyr.words[1].end,104.848)
        self.assertEqual(lyr.words[2].start,104.848)
        self.assertEqual(lyr.words[3].start,105.2)
        self.assertEqual(Q.trim_same_voice_tails(lyr),0)

    def test_tail_trim_preserves_duets_backing_manual_edits_and_uncertain_phrases(self):
        for variant in ('voice','both','backing','locked','keep','fixed','early','tiny'):
            lyr = L.parse('Whole phrase\nNext phrase')
            for word, times in zip(lyr.words, [(1,2),(2,4),(3,3.4),(3.4,4.5)]):
                word.start,word.end = times
            left,right = lyr.lines
            fixed = []
            if variant=='voice': right.voice=2
            if variant=='both': left.voice=right.voice=3
            if variant=='backing': right.backing=True
            if variant=='locked': left.lock=True
            if variant=='keep': left.keep=True
            if variant=='fixed': fixed=[id(left)]
            if variant=='early': right.words[0].start=1.5
            if variant=='tiny': right.words[0].start=2.02
            self.assertEqual(Q.trim_same_voice_tails(lyr,fixed),0,variant)
            self.assertEqual(left.words[-1].end,4,variant)

    def test_a_continuing_last_vowel_is_extended_to_the_first_silence(self):
        import numpy as np
        lyr = L.parse('To the ground\nNext line')
        for word, times in zip(lyr.words, [(1,1.1),(1.1,1.2),(1.2,1.5),(5,5.3),(5.3,5.8)]):
            word.start,word.end = times
        signal = np.zeros(160000,dtype=np.float32)
        signal[16000:56000] = .2
        self.assertEqual(Q.extend_sustained_tails(lyr,signal,10),1)
        self.assertAlmostEqual(lyr.words[2].end,3.54)
        self.assertEqual(lyr.words[2].start,1.2)
        self.assertEqual((lyr.words[3].start,lyr.words[3].end),(5,5.3))

    def test_tail_recovery_does_not_cross_a_real_pause_or_manual_boundary(self):
        import numpy as np
        for variant in ('pause','mark','fixed','locked','next','unending'):
            lyr = L.parse('Ground\nNext')
            for w,a,b in zip(lyr.words,(1,5),(1.5,5.8)):
                w.start,w.end = a,b
            signal = np.zeros(160000,dtype=np.float32)
            signal[16000:56000] = .2
            holes,fixed = [],[]
            if variant=='pause': signal[24000:30400] = 0
            if variant=='mark': holes=[(2,4)]
            if variant=='fixed': fixed=[id(lyr.lines[0])]
            if variant=='locked': lyr.lines[0].lock=True
            if variant=='next': lyr.words[1].start=2
            if variant=='unending': signal[16000:] = .2
            Q.extend_sustained_tails(lyr,signal,10,holes,fixed)
            self.assertEqual(lyr.words[0].end,1.5,variant)

    @unittest.skipUnless(os.environ.get('KARAOKE_QWEN_SMOKE_AUDIO'), 'real model smoke test is opt-in')
    def test_real_model_builds_a_project_with_the_selected_engine(self):
        from kstudio import project as P
        with tempfile.TemporaryDirectory(prefix='karaoke_qwen_smoke_') as folder:
            text=os.path.join(folder,'lyrics.txt')
            with open(text,'w',encoding='utf-8') as f:
                f.write('The quick brown fox jumps over the lazy dog.\n')
            path=P.create(os.environ['KARAOKE_QWEN_SMOKE_AUDIO'],text,folder,
                          align_engine='qwen',language='en',separate=False)
            data=P.load(path)
            self.assertEqual(data['engine'],'qwen')
            self.assertEqual(data['model'],'qwen3-forcedaligner-0.6b')
            words=data['lines'][0]['words']
            self.assertEqual(len(words),9)
            self.assertTrue(all(0 <= w['t'] < w['t']+w['d'] <= data['duration']+.001 for w in words))
            self.assertTrue(all(a['t']+a['d'] <= b['t']+.001 for a,b in zip(words,words[1:])))


if __name__ == '__main__':
    unittest.main()
