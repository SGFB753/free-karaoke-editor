"""Read-only real-model timing diagnostics for an existing project.

Run with the Qwen-enabled Python environment and a project folder argument.
No project files are written. Structural fault counts are not ground-truth
accuracy measurements: listen to the resulting phrase boundaries as well.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
from kstudio import audio as AU, lang as LG, lyrics as L, models as M, qwen as Q


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project')
    parser.add_argument('--skip-baseline', action='store_true')
    args = parser.parse_args()
    path = os.path.join(args.project, 'project.json')
    with open(path, 'rb') as file:
        before = file.read()
    data = json.loads(before)
    text = data['source_lyrics']
    source = data['source_audio']
    vocal = os.path.join(args.project, data.get('tracks', {}).get('vocals', ''))
    signal = vocal if os.path.isfile(vocal) else source
    duration = float(data['duration'])

    import numpy as np
    import torch
    Q.prepare_import()
    from qwen_asr import Qwen3ForcedAligner
    model = Qwen3ForcedAligner.from_pretrained(
        M.qwen_dir(), device_map='cpu', dtype=torch.float32, attn_implementation='sdpa')
    baseline = L.load(text)
    code = LG.resolve('auto', baseline.plain_text())
    pcm = AU.read_pcm_mono(source, 16000)
    audio = np.frombuffer(pcm.tobytes(), dtype='<i2').astype('float32') / 32768.0
    if not args.skip_baseline:
        raw = model.align(audio=(audio, 16000), text=baseline.plain_text(), language=Q.LANGUAGES[code])[0]
        try:
            Q.assign_words(baseline.words, raw, 0, lambda t: t, len(audio) / 16000)
            print('OLD ORIGINAL:', sum(w.end - w.start <= .005 for w in baseline.words), 'zero words', flush=True)
        except ValueError as exc:
            print('OLD ORIGINAL rejected:', str(exc), flush=True)

    fresh = L.load(text)
    faults = Q._faults
    snapshots = []

    def observe(lines, holes=()):
        result = faults(lines, holes)
        if len(lines) == len([ln for ln in fresh.lines if not ln.backing]):
            snapshots.append(([(w.start, w.end) for ln in lines for w in ln.words], result))
        return result

    start = time.monotonic()
    with patch.object(Q, '_faults', side_effect=observe):
        Q.align_qwen(fresh, signal, duration, code, model=model, isolated=signal == vocal,
                     fallback_audio=source, log=lambda msg: print(msg, flush=True))
    for label, (words, scores) in (('STEM COARSE', snapshots[0]), ('NEW RAW', snapshots[-1])):
        print(label, 'zero words:', sum(b - a <= .005 for a, b in words),
              'suspect lines:', [i + 1 for i, score in enumerate(scores) if score])
    print('SECONDS:', round(time.monotonic() - start, 1))
    for i, line in enumerate(fresh.lines):
        print(i + 1, line.text, [(w.text, round(w.start, 3), round(w.end, 3)) for w in line.words])
    with open(path, 'rb') as file:
        assert hashlib.sha256(file.read()).digest() == hashlib.sha256(before).digest(), 'Project changed during check'
    print('Project unchanged.')


if __name__ == '__main__':
    main()
