# CW Morse Decoder (GNU Radio + PyQt5)

A real-time CW (Morse code) decoder built as a GNU Radio flowgraph.

The application listens to an audio input stream, detects Morse keying transitions, classifies dits and dahs by timing, and outputs decoded text in a small Qt GUI.

## Features

- Live decoding from system audio input
- GUI text output with auto-scroll and clear button
- Console debug output (mirrors decoded characters)
- Farnsworth-aware timing split (character speed vs spacing speed)
- Built-in Morse tree for A-Z and 0-9

## Signal Pipeline

1. Audio source (default soundcard input)
2. Low-pass filter
3. Envelope extraction (signal squared)
4. Smoothing (single-pole IIR)
5. Threshold to binary on/off stream
6. Edge/timing analysis
7. Morse symbol decoding
8. Text output to GUI and stdout

## Requirements

- Python 3.8+
- GNU Radio with Qt GUI support
- PyQt5
- numpy
- pmt (included with GNU Radio Python bindings)

## Install

Install Python dependencies:

```bash
pip install gnuradio PyQt5 numpy
```

Notes:

- On many systems, GNU Radio is easier to install via a system package manager or conda.
- If `pip install gnuradio` fails on your platform, install GNU Radio using your OS method, then verify Python can import `gnuradio`.

## Run

```bash
python cw_decoder.py
```

When running, tune your receiver so the CW tone is centered near the expected frequency and routed into your default audio input.

## Configuration (in code)

Adjust these constants in `cw_decoder.py` inside `CWFlowgraph`:

- `SAMPLE_RATE = 8000`
- `AUDIO_FREQ = 700` (documented target tone; informational in current code)
- `LPF_CUTOFF = 150`
- `LPF_TRANS = 50`
- `AVG_LEN = 400`
- `THRESHOLD = 0.1`
- `CHAR_DIT_MS = 60`
- `FARN_DIT_MS = 150`

## Tuning Tips

- If decoding misses weak signals, lower `THRESHOLD` slightly.
- If noise causes false characters, increase `THRESHOLD` or `AVG_LEN`.
- If dits/dahs are confused, tune `CHAR_DIT_MS` to match sending speed.
- If spacing between letters/words is wrong, tune `FARN_DIT_MS`.
- Keep your receiver tone and audio routing stable to avoid timing jitter.

## Supported Characters

- Letters: A-Z
- Digits: 0-9

Unknown or invalid symbol paths decode as `?`.

## Troubleshooting

- No text appears:
  - Check microphone/line input selection in your OS.
  - Confirm audio is reaching the application input path.
  - Verify a clear CW tone is present.
- Import errors:
  - Confirm GNU Radio and PyQt5 are installed in the same Python environment.
- GUI opens but decoding is poor:
  - Re-tune threshold and timing constants for your signal.

## File Layout

- `cw_decoder.py`: Full decoder implementation and GUI entry point.

## License

Add your preferred license information here.
