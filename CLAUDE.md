# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the application

```bash
# Live audio (system default input)
python frontend_audio.py

# Named audio device
python frontend_audio.py --device hw:1,0

# Decode a WAV file
python frontend_audio.py --file recording.wav

# List available audio input devices (requires pip install sounddevice)
python frontend_audio.py --list-devices

# RTL-SDR / gr-osmosdr source
python frontend_sdr.py --freq 14.025e6
python frontend_sdr.py --freq 7.030e6 --gain 40 --ppm -3 --args "rtl=0"
```

There are no tests or build steps — the project runs directly with Python.

## Architecture

`cw_decoder.py` is the core module (import only, no `main()`). The two frontend scripts are the entry points.

**Decode pipeline** (pure Python, no GR):
- `EdgeDetector` — converts a binary float sample stream (0.0/1.0) to `(kind, symbol)` events by counting run-lengths and computing durations in ms
- `TimingAnalyzer` — classifies durations as dit/dah (pulse) or intra/letter/word gap (silence), maintaining the current symbol buffer; uses two thresholds: `char_dit_ms` (character speed) and `farn_dit_ms` (Farnsworth spacing)
- `MorseDecoder` — walks a binary tree keyed on `.`/`-` sequences to map symbols to characters

**GnuRadio layer:**
- `CWDecoderBlock(gr.sync_block)` — wraps `EdgeDetector` + `MorseDecoder`; input: float32 binary stream; output: PMT messages on port `decoded`
- `CWSignalPipeline` — not a GR block; a plain Python helper that instantiates and wires the signal-conditioning GR blocks: `fir_filter_fff` (LPF) → `multiply_ff` (square for envelope) → `single_pole_iir_filter_ff` (smooth) → `threshold_ff` → `CWDecoderBlock`. Call `pipeline.connect_source(tb, source_block)` to attach any float32 GR source. Access `pipeline.cw` for the message port.
- `CWDecoderWidget(Qt.QWidget)` — scrolling text display; call `on_message(pmt_msg)` from a `qtgui.msg_sink` msghandler

**frontend_audio.py** uses `audio.source` (live) or `blocks.wavfile_source` + `blocks.throttle` (file), then feeds into `CWSignalPipeline`.

**frontend_sdr.py** uses `osmosdr.source` → `fir_filter_ccf` (complex channel filter + decimate 250 kHz → 8 kHz) → `complex_to_mag` (envelope) → `CWSignalPipeline`.

## Key tuning constants

All constants are module-level in each frontend file (edit in source):

| Constant | Default | Effect |
|---|---|---|
| `SAMPLE_RATE` | 8000 Hz | Must match audio source rate |
| `LPF_CUTOFF` | 150 Hz | Low-pass cutoff before squaring |
| `AVG_LEN` | 400 samples | IIR smoothing window (~50 ms) |
| `THRESHOLD` | 0.1 | Key-on/off envelope level |
| `CHAR_DIT_MS` | 60 ms | Dit length at character speed (~18 WPM) |
| `FARN_DIT_MS` | 150 ms | Dit length for inter-character gaps |

For SDR: `SDR_RATE` (250 000 Hz), `CHAN_BW` (±500 Hz around carrier).

## Dependencies

- GNU Radio with Python bindings and `gr-qtgui` (`gnuradio`, `pmt`)
- PyQt5
- numpy
- `gr-osmosdr` — required only for `frontend_sdr.py`
- `sounddevice` — optional, only for `--list-devices` in `frontend_audio.py`

GNU Radio is typically installed via system package manager or conda rather than pip.
