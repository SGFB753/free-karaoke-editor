"""Exercise the real MP4 frame renderer on short endings and final backing."""
import copy
import os
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import video as V


class EndCountdownTests(unittest.TestCase):
    def render_pill(self, lines, at, duration=20):
        payload={'data':{'title':'Test','duration':duration,'lines':copy.deepcopy(lines)}}
        with tempfile.TemporaryDirectory() as folder:
            audio=os.path.join(folder,'audio.wav')
            with wave.open(audio,'wb') as stream:
                stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000)
                stream.writeframes(b'\0\0'*int(duration*8000))
            out=os.path.join(folder,'frame.png')
            args=SimpleNamespace(width=640,height=360,fps=30,crf=30,preset='ultrafast',font=None,
                                 intro=False,card=False,start=0,seconds=0,audio='minus',timings=None,
                                 output=out,still=at)
            real=V.pill_text
            with patch.object(V,'pill_text',wraps=real) as pill:
                V.render(payload,audio,out,args)
            self.assertTrue(os.path.isfile(out))
            return pill.call_args_list

    @staticmethod
    def line(start,end,backing=False):
        return dict(text='(back)' if backing else 'lead',start=start,end=end,
                    backing=backing,voice=1,words=[{'w':'back' if backing else 'lead',
                                                  't':start,'d':end-start,'s':1}])

    def test_short_ending_counts_down_and_stops_during_last_three_seconds(self):
        lines=[self.line(4,8),self.line(8,10.56,True)]
        for at in (10.6,12,16,17):
            calls=self.render_pill(lines,at)
            self.assertEqual(len(calls),1,at)
            self.assertIsNone(calls[0].args[2])
            self.assertAlmostEqual(calls[0].args[3],20-at)
        self.assertEqual(self.render_pill(lines,17.1),[])
        self.assertEqual(self.render_pill(lines,19.9),[])

    def test_final_backing_finishes_before_the_end_count_is_allowed(self):
        lines=[self.line(4,8),self.line(9,10.56,True)]
        self.assertEqual(self.render_pill(lines,8.5),[])
        self.assertEqual(self.render_pill(lines,9.5),[])

    def test_a_lead_outlasting_the_last_backing_still_sings_before_the_count(self):
        lines=[self.line(4,12),self.line(8,10.56,True)]
        self.assertEqual(self.render_pill(lines,11),[])
        self.assertEqual(len(self.render_pill(lines,12.5)),1)

    def test_short_interludes_remain_unlabelled(self):
        self.assertEqual(self.render_pill([self.line(1,3),self.line(8,12)],5),[])

    def test_long_interludes_keep_their_countdown(self):
        calls=self.render_pill([self.line(1,3),self.line(15,17)],5)
        self.assertEqual(len(calls),1)
        self.assertIsNotNone(calls[0].args[2])
        self.assertEqual(calls[0].args[3],10)


if __name__=='__main__': unittest.main()
