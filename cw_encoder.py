"""
CW Morse Encoder — core module
==============================
Provides:
  MorseEncoder    – Text → sequence of (kind, duration_ms) timing events
                    using standard CW timing with optional Farnsworth spacing.
  CWAudioEncoder  – Converts events to a float32 numpy audio waveform and
                    writes 16-bit PCM WAV files.

Timing model
------------
All element durations are derived from character speed (char_wpm):
  char_dit_ms = 1200 / char_wpm

Inter-character and inter-word gaps use Farnsworth timing (farn_wpm ≤ char_wpm):
  farn_dit_ms = (60000/farn_wpm − 31·char_dit_ms) / 19

When farn_wpm == char_wpm the two are equal (no Farnsworth stretching).
"""

import wave
import numpy as np


# ── Morse code table ───────────────────────────────────────────────────────────

MORSE_CODES = {
    'A': '.-',    'B': '-...', 'C': '-.-.', 'D': '-..',
    'E': '.',     'F': '..-.',  'G': '--.',  'H': '....',
    'I': '..',    'J': '.---', 'K': '-.-',  'L': '.-..',
    'M': '--',    'N': '-.',   'O': '---',  'P': '.--.',
    'Q': '--.-',  'R': '.-.',  'S': '...',  'T': '-',
    'U': '..-',   'V': '...-', 'W': '.--',  'X': '-..-',
    'Y': '-.--',  'Z': '--..',
    '0': '-----', '1': '.----', '2': '..---', '3': '...--',
    '4': '....-', '5': '.....', '6': '-....', '7': '--...',
    '8': '---..', '9': '----.',
    '.': '.-.-.-', ',': '--..--', '?': '..--..', '/': '-..-.',
    '-': '-....-', '(': '-.--.', ')': '-.--.-',
}


# ── Timing and event generation ────────────────────────────────────────────────

class MorseEncoder:
    """
    Converts text to a flat sequence of ``('tone' | 'silence', duration_ms)``
    timing events suitable for audio synthesis.

    Parameters
    ----------
    char_wpm : int
        Character speed in words per minute (controls dit/dah/intra-char timing).
    farn_wpm : int or None
        Overall (Farnsworth) speed.  Must be ≤ char_wpm.  Defaults to char_wpm
        (no Farnsworth stretching).

    Raises
    ------
    ValueError
        If farn_wpm > char_wpm.
    """

    def __init__(self, char_wpm=20, farn_wpm=None):
        if farn_wpm is None:
            farn_wpm = char_wpm
        if farn_wpm > char_wpm:
            raise ValueError(
                f'farn_wpm ({farn_wpm}) must be ≤ char_wpm ({char_wpm})'
            )

        self.char_dit_ms = 1200.0 / char_wpm

        # PARIS = 31 units of element + intra-char content, 19 units of gaps.
        char_content_ms  = 31.0 * self.char_dit_ms
        word_total_ms    = 60_000.0 / farn_wpm
        self.farn_dit_ms = (word_total_ms - char_content_ms) / 19.0

    def encode(self, text):
        """
        Return a list of ``(kind, duration_ms)`` tuples.

        ``kind`` is ``'tone'`` or ``'silence'``.
        Unknown characters are silently skipped.
        """
        events = []
        words = text.upper().split()
        for wi, word in enumerate(words):
            chars = [ch for ch in word if ch in MORSE_CODES]
            for ci, char in enumerate(chars):
                code = MORSE_CODES[char]
                for ei, element in enumerate(code):
                    duration = self.char_dit_ms if element == '.' else 3 * self.char_dit_ms
                    events.append(('tone', duration))
                    if ei < len(code) - 1:
                        events.append(('silence', self.char_dit_ms))
                if ci < len(chars) - 1:
                    events.append(('silence', 3 * self.farn_dit_ms))
            if wi < len(words) - 1:
                events.append(('silence', 7 * self.farn_dit_ms))
        return events


# ── Audio synthesis ────────────────────────────────────────────────────────────

class CWAudioEncoder:
    """
    Synthesises CW Morse audio from text.

    Parameters
    ----------
    char_wpm    : int   — character speed (WPM)
    farn_wpm    : int   — Farnsworth overall speed (WPM, ≤ char_wpm)
    tone_hz     : int   — sidetone frequency (Hz)
    sample_rate : int   — output sample rate (Hz)

    Methods
    -------
    encode(text)              → np.ndarray (float32, −1.0 … 1.0)
    write_wav(samples, path)  → writes 16-bit mono PCM WAV
    """

    _RAMP_MS = 5  # cosine ramp to suppress key clicks

    def __init__(self, char_wpm=20, farn_wpm=None, tone_hz=700, sample_rate=8000):
        self.tone_hz     = tone_hz
        self.sample_rate = sample_rate
        self._morse      = MorseEncoder(char_wpm, farn_wpm)

    def _n_samples(self, duration_ms):
        return max(1, int(self.sample_rate * duration_ms / 1000.0))

    def _tone_segment(self, duration_ms):
        n     = self._n_samples(duration_ms)
        t     = np.arange(n, dtype=np.float32) / self.sample_rate
        audio = np.sin(2.0 * np.pi * self.tone_hz * t, dtype=np.float32)
        # cosine ramp-in / ramp-out to eliminate key clicks
        ramp_n = min(self._n_samples(self._RAMP_MS), n // 2)
        if ramp_n > 0:
            ramp = (0.5 - 0.5 * np.cos(np.pi * np.arange(ramp_n) / ramp_n)).astype(np.float32)
            audio[:ramp_n]  *= ramp
            audio[-ramp_n:] *= ramp[::-1]
        return audio

    def _silence_segment(self, duration_ms):
        return np.zeros(self._n_samples(duration_ms), dtype=np.float32)

    def encode(self, text):
        """Return a float32 numpy array containing the CW audio for *text*."""
        events = self._morse.encode(text)
        if not events:
            return np.zeros(0, dtype=np.float32)
        parts = [
            self._tone_segment(ms) if kind == 'tone' else self._silence_segment(ms)
            for kind, ms in events
        ]
        return np.concatenate(parts)

    def write_wav(self, samples, path):
        """Write *samples* (float32, −1…1) to a 16-bit mono PCM WAV at *path*."""
        pcm16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(path, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm16.tobytes())
