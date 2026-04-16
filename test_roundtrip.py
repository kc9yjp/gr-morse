"""
Round-trip test: encode text → WAV samples → decode → original text.

Signal conditioning mirrors the GR pipeline:
  square → IIR smooth (avg_len=400) → threshold (0.1) → EdgeDetector

Run with:  python -m pytest test_roundtrip.py   or   python test_roundtrip.py
"""

import numpy as np
import pytest

from cw_encoder import CWAudioEncoder
from cw_decoder import EdgeDetector, MorseDecoder

SAMPLE_RATE = 8000
CHAR_WPM    = 20
CHAR_DIT_MS = 1200.0 / CHAR_WPM   # 60 ms
FARN_DIT_MS = CHAR_DIT_MS
AVG_LEN     = 400
THRESHOLD   = 0.1


def _condition(samples):
    """Square → IIR smooth → hard threshold, matching CWSignalPipeline."""
    alpha = 2.0 / AVG_LEN
    smoothed = np.empty_like(samples)
    y = 0.0
    for i, x in enumerate(samples * samples):
        y = alpha * float(x) + (1.0 - alpha) * y
        smoothed[i] = y
    return (smoothed >= THRESHOLD).astype(np.float32)


def _decode(binary, sample_rate=SAMPLE_RATE,
            char_dit_ms=CHAR_DIT_MS, farn_dit_ms=FARN_DIT_MS):
    edge  = EdgeDetector(sample_rate, char_dit_ms, farn_dit_ms)
    morse = MorseDecoder()
    chars = []

    def _handle(kind, symbol):
        if kind == 'intra' or not symbol:
            return
        letter = morse.decode_symbol(symbol)
        chars.append(letter)
        if kind == 'word':
            chars.append(' ')

    for sample in binary:
        result = edge.push_sample(sample)
        if result:
            _handle(*result)

    result = edge.flush()
    if result:
        _handle(*result)

    return ''.join(chars)


def encode_and_decode(text, char_wpm=CHAR_WPM, tone_hz=700):
    enc     = CWAudioEncoder(char_wpm=char_wpm, farn_wpm=char_wpm,
                              tone_hz=tone_hz, sample_rate=SAMPLE_RATE)
    samples = enc.encode(text)
    binary  = _condition(samples)
    char_dit_ms = 1200.0 / char_wpm
    return _decode(binary, char_dit_ms=char_dit_ms, farn_dit_ms=char_dit_ms)


def test_alphanumeric_roundtrip():
    assert encode_and_decode("abc123") == "ABC123"

def test_single_letter():
    assert encode_and_decode("e") == "E"

def test_multi_word():
    assert encode_and_decode("cq de") == "CQ DE"

def test_numbers():
    assert encode_and_decode("73") == "73"


if __name__ == '__main__':
    tests = [
        test_alphanumeric_roundtrip,
        test_single_letter,
        test_multi_word,
        test_numbers,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print(f'PASS  {t.__name__}')
        except AssertionError as e:
            print(f'FAIL  {t.__name__}: {e}')
            failed += 1
    raise SystemExit(failed)
