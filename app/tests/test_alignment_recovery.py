"""Recovery uses independent acoustic locations, never a failed time cursor."""
import sys
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from kstudio import alignment_recovery as R, lyrics as L, align as A, jobcontrol as JC


def transcript(items):
    return S(segments=[S(words=[S(word=text, start=a, end=b, probability=.9)
                                for text,a,b in items])])


class AnchorTests(unittest.TestCase):
    def test_split_asr_words_are_joined_without_changing_written_lyrics(self):
        lyrics = L.parse('North something grows\nSouth sunlight fades')
        result = transcript([('north',1,1.2),('some',1.2,1.4),('thing',1.4,1.6),('grows',1.6,2),
                             ('south',4,4.2),('sun',4.2,4.4),('light',4.4,4.6),('fades',4.6,5)])
        found = R.phrase_anchors(lyrics.lines, R.heard_words(result))
        self.assertEqual(found, {0:(1,2),1:(4,5)})
        self.assertEqual(lyrics.lines[0].text, 'North something grows')

    def test_repeated_chants_do_not_pull_a_later_unique_verse_to_the_wrong_repetition(self):
        lyrics = L.parse('North river flows\n'+'echo '*13+'\nSouth river burns\nNorth river flows')
        result = transcript([('north',1,1.2),('river',1.2,1.4),('flows',1.4,2),
            ('echo',4,4.2),('echo',4.3,4.5),('south',12,12.2),('river',12.2,12.4),('burns',12.4,13),
            ('north',20,20.2),('river',20.2,20.4),('flows',20.4,21)])
        found = R.phrase_anchors(lyrics.lines, R.heard_words(result))
        self.assertNotIn(1, found)
        self.assertEqual(found[2], (12,13))
        self.assertEqual(found[3], (20,21))

    def test_unheard_middle_gets_its_own_bounded_search_not_the_rest_of_the_song(self):
        jobs = R.search_windows(3, {0:(2,3),2:(7,8)},0,10)
        self.assertEqual([j[:2] for j in jobs], [(0,1),(1,2),(2,3)])
        self.assertGreater(jobs[1][2],3)
        self.assertLess(jobs[1][3],7)
        self.assertEqual(jobs[2][3],10)

    def test_conflicting_edge_context_is_merged_instead_of_cutting_off_a_word(self):
        jobs = R.search_windows(3,{0:(1,3.5),1:(3,5),2:(7,8)},0,10)
        self.assertEqual(jobs[0][:2], (0,2))
        self.assertGreater(jobs[0][3],5)

    def test_short_model_inputs_get_neighbour_context_without_setting_word_durations(self):
        jobs=R.search_windows(3,{0:(.1,.3),1:(.5,.7),2:(2,3)},0,4,min_seconds=1.)
        self.assertTrue(all(hi-lo>=1 for _,_,lo,hi in jobs))
        self.assertEqual(jobs[0][0],0)
        self.assertEqual(jobs[-1][1],3)

    def test_complementary_sources_are_combined_without_using_a_wrong_late_repeat(self):
        anchors, origins=R.merge_anchors([
            ({0:(1,2),2:(20,21),3:(30,31)},{}),
            ({1:(10,11),2:(50,51),4:(40,41)}, {})])
        self.assertEqual(sorted(anchors),[0,1,2,3,4])
        self.assertEqual(anchors[2],(20,21))
        self.assertEqual(origins[1],1)

    def test_flat_zero_confidence_suffix_is_detected_without_any_large_gaps(self):
        lyrics=L.parse('\n'.join('Distinct phrase '+str(i) for i in range(10)))
        for i,line in enumerate(lyrics.lines):
            for j,word in enumerate(line.words):
                word.start=word.end=30 if i>=4 else i*2+j*.3
                if i<4: word.end+=.25
                word.prob=.8 if i<4 else 0
        self.assertEqual(A._lost_alignment_index(lyrics.lines),4)


class RecoveryTests(unittest.TestCase):
    def fixture(self):
        return L.parse('North river\nSouth garden\nBright sunlight\nQuiet evening')

    def model(self, fail_first=False):
        good=transcript([('north',1,1.3),('river',1.3,2),('south',3,3.3),('garden',3.3,4),
                         ('bright',5,5.3),('sunlight',5.3,6),('quiet',7,7.3),('evening',7.3,8)])
        class Model:
            def transcribe(self, signal, **opts):
                return good if signal[0] else transcript([('unrelated',1,2)])
            def align(self, signal, text, **opts):
                if fail_first and text.startswith('North'):
                    raise ValueError('cannot hear this phrase')
                words=text.split()
                return S(segments=[S(words=[S(word=t,start=.1+j*.25,end=.3+j*.25,probability=.8)
                                             for j,t in enumerate(words)])])
        return Model()

    def test_alternate_source_is_used_only_when_it_matches_more_supplied_phrases(self):
        lyrics=self.fixture()
        plan=R.recover(lyrics.lines,np.zeros(160000),self.model(),'en',0,0,lambda t:t+20,lambda _:None,
                       sources=[np.zeros(160000),np.ones(160000)])
        self.assertIsNotNone(plan)
        self.assertFalse(plan.failed)
        self.assertEqual(plan.windows[0][2],20)
        self.assertGreater(lyrics.lines[2].words[0].start,24)

    def test_one_unheard_phrase_does_not_abort_the_following_recovery_windows(self):
        lyrics=self.fixture()
        plan=R.recover(lyrics.lines,np.ones(160000),self.model(True),'en',0,0,lambda t:t,lambda _:None)
        self.assertEqual(plan.failed,{0})
        self.assertIsNone(lyrics.lines[0].words[0].start)
        self.assertGreater(lyrics.lines[3].words[0].start,6)

    def test_phrase_uses_its_own_recording_even_when_neighbours_prefer_another(self):
        lyrics=self.fixture()
        model=self.model()
        transcripts=[transcript([('north',1,1.3),('river',1.3,2),
                                ('bright',5,5.3),('sunlight',5.3,6),
                                ('quiet',7,7.3),('evening',7.3,8)]),
                     transcript([('south',3,3.3),('garden',3.3,4)])]
        observed=[]
        original=model.align
        def infer(signal,text,**opts):
            observed.append((text,float(signal[0])))
            return original(signal,text,**opts)
        with patch.object(model,'transcribe',side_effect=transcripts), \
                patch.object(model,'align',side_effect=infer):
            plan=R.recover(lyrics.lines,np.ones(160000),model,'en',0,0,lambda t:t,lambda _:None,
                           sources=[np.ones(160000),np.full(160000,2.)])
        self.assertFalse(plan.failed)
        self.assertIn(('South garden',2.),observed)
        self.assertIn(('Bright sunlight',1.),observed)

    def test_unrelated_transcription_cannot_replace_existing_timing(self):
        lyrics=self.fixture()
        lyrics.lines[0].words[0].start=42
        plan=R.recover(lyrics.lines,np.zeros(160000),self.model(),'en',0,0,lambda t:t,lambda _:None)
        self.assertIsNone(plan)
        self.assertEqual(lyrics.lines[0].words[0].start,42)

    def test_cancellation_stops_before_another_model_call(self):
        model=self.model()
        with patch.object(JC,'checkpoint',side_effect=JC.Cancelled), patch.object(model,'transcribe') as run:
            with self.assertRaises(JC.Cancelled):
                R.recover(self.fixture().lines,np.ones(160000),model,'en',0,0,lambda t:t,lambda _:None)
            run.assert_not_called()


if __name__=='__main__':
    unittest.main()
