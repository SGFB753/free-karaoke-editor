"""Acoustic evidence for a continuing sung vowel on an isolated vocal stem.

Energy alone includes breath, reverb and other words. Track a periodic tone
from the existing final syllable instead; this is not a proportional timing fill.
"""
import math


class HarmonicTails:
    def __init__(self, audio):
        import numpy as np
        self.audio = audio
        self.cache = {}
        self.bands = np.geomspace(20, 575, 40).astype(int)

    def feature(self, index):
        import numpy as np
        if index in self.cache:
            return self.cache[index]
        center = index * 320  # 20 ms at 16 kHz
        frame = np.asarray(self.audio[max(0, center - 512):center + 512], dtype='float64').copy()
        if len(frame) < 480:
            return (0., 0., 0., None)
        frame -= frame.mean()
        energy = frame ** 2
        rms = float(np.sqrt(np.mean(energy)))
        if rms < 1e-7:
            result = (rms, 0., 0., None)
        else:
            sums = np.r_[0., np.cumsum(energy)]
            ac = np.fft.irfft(abs(np.fft.rfft(frame, 2048)) ** 2)[:256]
            # 70–670 Hz, including octave aliases of higher sung notes.
            lags = np.arange(24, min(230, len(frame) // 2))
            norm = np.sqrt(np.maximum(sums[len(frame) - lags] * (sums[-1] - sums[lags]), 1e-20))
            corr = ac[lags] / norm
            peaks = np.where((corr[1:-1] >= corr[:-2]) & (corr[1:-1] >= corr[2:]))[0] + 1
            if len(peaks):
                best = float(np.max(corr[peaks]))
                # Prefer the shortest credible period. The third period of
                # another note can resemble an octave of the original one.
                credible = peaks[corr[peaks] >= max(.6, best * .92)]
                pick = credible[0] if len(credible) else peaks[np.argmax(corr[peaks])]
            else:
                pick = np.argmax(corr)
            # Smooth away individual harmonics to compare vowel timbre rather
            # than matching whichever FFT bin the fundamental fell into.
            spectrum = np.log(np.maximum(abs(np.fft.rfft(frame * np.hanning(len(frame)), 2048)), 1e-8))
            cepstrum = np.fft.irfft(spectrum)
            cepstrum[25:-24] = 0
            envelope = np.fft.rfft(cepstrum).real[self.bands]
            envelope -= envelope.mean()
            envelope /= max(float(np.linalg.norm(envelope)), 1e-10)
            result = (rms, float(16000 / lags[pick]), float(np.clip(corr[pick], -1, 1)), envelope)
        self.cache[index] = result
        return result

    def end(self, start, edge, limit, next_phrase=False):
        """None = no reliable tone; a float = observed end, even if very close.

        Small pitch bends belong to one note. A sustained loss of periodicity,
        vowel timbre or pitch continuity ends it. A known following
        phrase can bound continuous singing; a user mark/arbitrary cap cannot.
        """
        import numpy as np
        boundary = int(edge / .02)
        seed = [self.feature(j) for j in range(int(max(start, edge - .3) / .02), boundary)]
        voiced = [f for f in seed if f[2] >= .75]
        if len(voiced) < 5:
            return None
        base = max(voiced, key=lambda f: f[0] * f[2])[1]

        def distance(pitch):
            if pitch <= 0:
                return 1.
            return abs(math.log2(pitch / base))

        stable = [f for f in voiced if distance(f[1]) < .22]
        if len(stable) < 5:
            return None
        threshold = float(np.median([f[0] for f in stable])) * .22
        timbre = np.mean([f[3] for f in stable], axis=0)
        timbre /= max(float(np.linalg.norm(timbre)), 1e-10)
        last, quiet = boundary - 1, 0
        stopped = False
        for j in range(boundary, int(limit / .02)):
            energy, pitch, confidence, envelope = self.feature(j)
            if (energy >= threshold and confidence >= .6 and distance(pitch) < .22
                    and envelope is not None and float(timbre @ envelope) >= .4):
                last, quiet = j, 0
            else:
                quiet += 1
                if quiet >= 8:
                    stopped = True
                    break
        if not stopped and not next_phrase:
            return None
        return min(limit, (last + 1) * .02 + .04)
