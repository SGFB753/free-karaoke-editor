"""Cancellation must stop work without treating it as a model failure."""
import os
import sys
import tempfile
import threading
import time
import unittest
import json
from urllib.request import Request, urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import studio as ST
from kstudio import jobcontrol as JC, project as P, winproc as WP


class CancellationTests(unittest.TestCase):
    def wait_done(self, jid):
        deadline = time.monotonic() + 5
        while not ST.JOBS[jid]['done'] and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(ST.JOBS[jid]['done'])

    def test_cancelled_retiming_never_replaces_saved_data(self):
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory(prefix='karaoke_cancel_') as folder:
            P.save(folder, {'lines':[{'text':'original'}]})
            with open(os.path.join(folder,P.PROJECT_FILE),'rb') as f:
                before = f.read()
            def work(log):
                entered.set()
                release.wait(3)
                P.save(folder, {'lines':[{'text':'replacement'}]})
            jid = ST.start_job('test timing',work,cancellable=True)
            self.assertTrue(entered.wait(3))
            self.assertTrue(ST.JOB_CONTROLS[jid].cancel())
            release.set()
            self.wait_done(jid)
            self.assertTrue(ST.JOBS[jid]['cancelled'])
            with open(os.path.join(folder,P.PROJECT_FILE),'rb') as f:
                self.assertEqual(f.read(),before)

    def test_commit_rejects_late_cancellation(self):
        control = JC.Control()
        with JC.scope(control):
            JC.commit()
            self.assertFalse(control.cancel())
            JC.checkpoint()

    def test_inference_loop_is_interrupted_without_model_fallback(self):
        entered = threading.Event()
        namespace = {'entered': entered}
        exec(compile('def inference():\n entered.set()\n while True:\n  pass\n',
                     '/test/torch/inference.py', 'exec'), namespace)
        jid = ST.start_job('inference', lambda log: namespace['inference'](), cancellable=True)
        self.assertTrue(entered.wait(3))
        self.assertTrue(ST.JOB_CONTROLS[jid].cancel())
        self.wait_done(jid)
        self.assertTrue(ST.JOBS[jid]['cancelled'])
        self.assertIsNone(ST.JOBS[jid]['error'])

    def test_cancel_api_reports_cancellation_not_success(self):
        entered, release = threading.Event(), threading.Event()
        def work(log):
            entered.set()
            release.wait(3)
            JC.checkpoint()
        jid=ST.start_job('api timing',work,cancellable=True)
        self.assertTrue(entered.wait(3))
        server=ThreadingHTTPServer(('127.0.0.1',0),ST.Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urlopen(Request(base+'/api/job/cancel',data=json.dumps({'id':jid}).encode(),
                                 headers={'Content-Type':'application/json'})) as response:
                self.assertTrue(json.load(response)['accepted'])
            release.set()
            self.wait_done(jid)
            with urlopen(base+'/api/job?id='+jid) as response:
                job=json.load(response)
            self.assertTrue(job['cancelled'])
            self.assertFalse(job['ok'])
            self.assertFalse(job['cancellable'])
        finally:
            release.set()
            server.shutdown()
            server.server_close()

    def test_cancelled_creation_cleans_only_its_new_folder(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='karaoke_cancel_create_') as root:
            source = os.path.join(root,'input.wav')
            lyrics = os.path.join(root,'input.txt')
            with open(source,'wb') as f: f.write(b'original audio')
            with open(lyrics,'w',encoding='utf-8') as f: f.write('Song words')
            control = JC.Control()
            def abort():
                control.cancel()
                JC.checkpoint()
            with self.assertRaises(JC.Cancelled):
                with patch('kstudio.audio.ffmpeg',side_effect=abort), JC.scope(control):
                    P.create(source,lyrics,root,separate=False)
            self.assertEqual(sorted(os.listdir(root)),['input.txt','input.wav'])

    def test_cancelled_backing_removal_keeps_all_project_files(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='karaoke_cancel_backing_') as folder:
            P.save(folder, {'duration':10, 'lines':[
                {'text':'Lead words','start':1,'end':3},
                {'text':'(Backing words)','start':3,'end':4,'backing':True}]})
            path=os.path.join(folder,P.PROJECT_FILE)
            with open(path,'rb') as f: before=f.read()
            control=JC.Control()
            def abort(*args,**kwargs):
                control.cancel()
                JC.checkpoint()
            with self.assertRaises(JC.Cancelled):
                with JC.scope(control), patch.object(ST,'timing_audio',return_value=('audio.wav',False)), \
                        patch.object(ST.AU,'ensure_on_path'), patch('kstudio.align.align',side_effect=abort):
                    ST.realign(folder,{'removeBacking':True},lambda msg: None)
            self.assertEqual(os.listdir(folder),[P.PROJECT_FILE])
            with open(path,'rb') as f: self.assertEqual(f.read(),before)

    def test_cancel_terminates_registered_helper(self):
        entered = threading.Event()
        def work(log):
            with WP.Popen([sys.executable,'-c','import time; time.sleep(30)']) as child:
                entered.set()
                child.wait()
                JC.checkpoint()
        jid = ST.start_job('helper',work,cancellable=True)
        self.assertTrue(entered.wait(3))
        self.assertTrue(ST.JOB_CONTROLS[jid].cancel())
        self.wait_done(jid)
        self.assertTrue(ST.JOBS[jid]['cancelled'])


if __name__ == '__main__':
    unittest.main()
