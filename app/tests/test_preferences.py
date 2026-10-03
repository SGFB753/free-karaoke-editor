"""Timing choice survives private browser sessions and rejects corrupt data."""
import os
import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from kstudio import preferences as P


class PreferencesTests(unittest.TestCase):
    def test_api_persists_and_rejects_foreign_or_invalid_requests(self):
        import studio as S
        with tempfile.TemporaryDirectory() as root, patch.object(S, "PROJECTS", root):
            server = ThreadingHTTPServer(('127.0.0.1', 0), S.Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                for engine, headers, code in (
                    ('qwen', {'Content-Type': 'application/json', 'Origin': 'https://foreign.example'}, 403),
                    ('other', {'Content-Type': 'application/json'}, 400)):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(base + '/api/preferences/timing',
                            data=json.dumps({'engine': engine}).encode(), headers=headers))
                    self.assertEqual(error.exception.code, code)
                self.assertIsNone(P.timing_engine(root))
                with urlopen(Request(base + '/api/preferences/timing',
                        data=b'{"engine":"qwen"}', headers={'Content-Type': 'application/json'})) as response:
                    self.assertEqual(json.load(response), {'engine': 'qwen'})
                with patch.object(S, 'capabilities', return_value={}):
                    with urlopen(base + '/api/state') as response:
                        self.assertEqual(json.load(response)['timingEngine'], 'qwen')
            finally:
                server.shutdown()
                server.server_close()

    def test_round_trip_and_validation(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(P.timing_engine(root))
            for engine in P.ENGINES:
                P.save_timing_engine(root, engine)
                self.assertEqual(P.timing_engine(root), engine)
            with self.assertRaises(ValueError):
                P.save_timing_engine(root, "unrecognised")
            self.assertEqual(P.timing_engine(root), "energy")
            self.assertEqual(os.listdir(root), [".timing-engine.json"])

    def test_corrupt_file_is_not_fatal(self):
        with tempfile.TemporaryDirectory() as root:
            for value in ("invalid json", "[]", "null", '{"engine":"other"}'):
                with open(os.path.join(root, ".timing-engine.json"), "w") as stream:
                    stream.write(value)
                self.assertIsNone(P.timing_engine(root))
            P.save_timing_engine(root, "qwen")
            self.assertEqual(P.timing_engine(root), "qwen")


if __name__ == "__main__":
    unittest.main()
