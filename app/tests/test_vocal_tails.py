"""Held-note recovery must follow the voice, not just a loud waveform."""
import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from kstudio import lyrics as L, qwen as Q, align as A


class HeldVowelTests(unittest.TestCase):
    def fixture(self):
        lyr=L.parse('A held vowel\nNext phrase')
        for w,start,end in zip(lyr.words,(1,1.2,1.4,4,4.4),(1.2,1.4,2,4.4,4.8)):
            w.start,w.end=start,end
        for ln in lyr.lines: ln.start,ln.end=ln.words[0].start,ln.words[-1].end
        return lyr

    def tone(self,end=4.8,pitch=220):
        samples=np.arange(160000)/16000
        return (.2*np.sin(samples*2*np.pi*pitch)*((samples>=1)&(samples<end))).astype('float32')

    def test_a_vowel_can_reach_the_next_phrase_without_a_long_silent_gap(self):
        lyr=self.fixture();before=[(w.start,w.end) for w in lyr.words]
        self.assertEqual(Q.extend_sustained_tails(lyr,self.tone(),10),1)
        self.assertAlmostEqual(lyr.lines[0].end,4,places=2)
        self.assertEqual([(w.start,w.end) for w in lyr.words[:-3]],before[:-3])
        self.assertEqual([(w.start,w.end) for w in lyr.lines[1].words],before[-2:])

    def test_a_pitch_change_ends_the_vowel_even_without_energy_drop(self):
        lyr=self.fixture();signal=self.tone()
        time=np.arange(len(signal))/16000
        signal[time>=2.7]=.2*np.sin(time[time>=2.7]*2*np.pi*340)
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertTrue(2.65<=lyr.lines[0].end<=2.8,lyr.lines[0].end)

    def test_noise_after_a_vowel_is_not_part_of_the_held_note(self):
        lyr=self.fixture();signal=self.tone()
        cut=int(2.7*16000)
        signal[cut:]=np.random.default_rng(42).normal(0,.15,len(signal)-cut)
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertTrue(2.65<=lyr.lines[0].end<=2.8,lyr.lines[0].end)

    def test_vibrato_and_a_gradual_fade_do_not_break_a_held_note(self):
        lyr=self.fixture()
        time=np.arange(160000)/16000
        fade=np.clip(1-(time-2)*.25,.4,1)
        signal=(.2*fade*np.sin(2*np.pi*220*time+2.5*np.sin(2*np.pi*5*time))*(time>=1)).astype('float32')
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertAlmostEqual(lyr.lines[0].end,4,places=2)

    def test_audible_unvoiced_consonants_after_the_vowel_are_not_cut_off(self):
        lyr=self.fixture();signal=self.tone(end=2.7)
        a,b=int(2.7*16000),int(3.1*16000)
        signal[a:b]=np.random.default_rng(17).normal(0,.15,b-a)
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertAlmostEqual(lyr.lines[0].end,3.14,places=2)

    def test_a_real_pause_is_not_crossed_when_the_same_note_returns(self):
        lyr=self.fixture();signal=self.tone()
        signal[int(2.6*16000):int(2.9*16000)]=0
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertTrue(2.55<=lyr.lines[0].end<=2.7,lyr.lines[0].end)

    def test_marks_manual_lines_and_unverified_timing_are_preserved(self):
        for kind in ('mark','lock','keep','manual','fixed','review','back','unheard'):
            lyr=self.fixture();opts={}
            if kind=='mark': opts['holes']=[(2.5,3.5)]
            if kind=='lock': lyr.lines[0].lock=True
            if kind=='keep': lyr.lines[0].keep=True
            if kind=='manual': lyr.fixed_line_indices={0}
            if kind=='fixed': opts['fixed']={id(lyr.lines[0])}
            if kind=='review': lyr.lines[0].timing_review=True
            if kind=='back': lyr.lines[0].backing=True
            if kind=='unheard': lyr.lines[0].words[-1].prob=.05
            Q.extend_sustained_tails(lyr,self.tone(),10,**opts)
            self.assertEqual(lyr.lines[0].end,2,kind)

    def test_neither_the_eight_second_cap_nor_audio_end_is_an_observed_note_end(self):
        lyr=self.fixture();lyr.lines=lyr.lines[:1]
        signal=self.tone(end=10)
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertEqual(lyr.lines[0].end,2)

    def test_the_whisper_postpass_uses_vocal_audio_and_respects_marks(self):
        for marked in (False,True):
            lyr=self.fixture();raw=(self.tone()*32767).astype('int16')
            with patch('kstudio.audio.read_pcm_mono',return_value=raw) as decode:
                A.refine_sustained_tails(lyr,'stem.wav',10,skip=[(2.5,3.5)] if marked else None)
            decode.assert_called_once_with('stem.wav',16000)
            self.assertAlmostEqual(lyr.lines[0].end,2 if marked else 4,places=2)

    def test_selected_phrase_can_use_its_unselected_neighbour_as_a_boundary(self):
        lyr=self.fixture();lyr.lines=lyr.lines[:1]
        raw=(self.tone()*32767).astype('int16')
        with patch('kstudio.audio.read_pcm_mono',return_value=raw):
            A.refine_sustained_tails(lyr,'stem',10,skip=[(4,10)],next_start=4)
        self.assertAlmostEqual(lyr.lines[0].end,4,places=2)

    def test_a_second_pass_does_not_walk_the_endpoint_forward(self):
        lyr=self.fixture();signal=self.tone(end=3)
        Q.extend_sustained_tails(lyr,signal,10)
        first=lyr.lines[0].end
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertEqual(lyr.lines[0].end,first)

    def test_unverified_words_keep_the_existing_silence_based_recovery(self):
        for kind in ('review','unheard'):
            lyr=self.fixture()
            if kind=='review': lyr.lines[0].timing_review=True
            else: lyr.lines[0].words[-1].prob=.05
            signal=np.zeros(160000,dtype='float32');signal[16000:48000]=.2
            Q.extend_sustained_tails(lyr,signal,10)
            self.assertAlmostEqual(lyr.lines[0].end,3.04)

    def test_a_word_that_has_already_ended_is_not_extended(self):
        lyr=self.fixture()
        self.assertEqual(Q.extend_sustained_tails(lyr,self.tone(end=2),10),0)
        self.assertEqual(lyr.lines[0].end,2)

    def test_same_pitch_echo_after_a_pause_cannot_restart_the_word(self):
        lyr=self.fixture();signal=self.tone(end=2)
        echo=self.tone(end=3.6)*.35
        echo[:int(2.3*16000)]=0
        signal+=echo
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertEqual(lyr.lines[0].end,2)

    def test_loud_nonperiodic_stem_noise_is_not_a_held_vowel(self):
        lyr=self.fixture()
        signal=np.random.default_rng(124).normal(0,.15,160000).astype('float32')
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertEqual(lyr.lines[0].end,2)

    def test_a_short_ambiguous_tonal_release_is_left_alone(self):
        lyr=self.fixture();signal=self.tone(end=2.2)
        cut=int(2.2*16000)
        signal[cut:]=np.random.default_rng(25).normal(0,.15,len(signal)-cut)
        Q.extend_sustained_tails(lyr,signal,10)
        self.assertEqual(lyr.lines[0].end,2)


if __name__=='__main__': unittest.main()
