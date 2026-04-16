"""
CW Decoder — SDR frontend
=========================
Uses an RTL-SDR (or any gr-osmosdr-compatible device) as the RF source.

The SDR is tuned to the CW carrier frequency.  A narrow complex bandpass
filter isolates the carrier, complex-to-magnitude gives the envelope, and
the result is decimated to audio rate before entering the standard CW
signal-conditioning pipeline.

Usage
-----
  python frontend_sdr.py --freq 14.025e6
  python frontend_sdr.py --freq 7.030e6 --gain 30 --ppm -3
  python frontend_sdr.py --freq 14.025e6 --args "rtl=0,bias=1"

Frequency and gain can also be adjusted live via the GUI controls.

Requirements
------------
  gr-osmosdr   (RTL-SDR, HackRF, bladeRF, …)
    Ubuntu/Debian:  sudo apt install gr-osmosdr
    conda-forge:    conda install -c conda-forge gr-osmosdr
"""

import argparse
import sys

try:
    import osmosdr
except ImportError:
    sys.exit(
        'gr-osmosdr not found.\n'
        'Install it (e.g. sudo apt install gr-osmosdr) to use the SDR frontend.'
    )

from gnuradio import gr, blocks, filter as gr_filter, qtgui
from gnuradio.filter import firdes
import pmt
from PyQt5 import Qt

from cw_decoder import CWSignalPipeline, CWDecoderWidget

# ── SDR / decimation parameters ────────────────────────────────────────────────
SDR_RATE      = 250_000   # Hz — SDR sample rate (must be supported by device)
AUDIO_RATE    =   8_000   # Hz — rate fed into the CW pipeline
CHAN_BW       =     500   # Hz — ±bandwidth around the carrier to keep
CHAN_TRANS    =     200   # Hz — channel filter transition width

# ── CW pipeline defaults ───────────────────────────────────────────────────────
LPF_CUTOFF    = 150       # Hz
LPF_TRANS     =  50       # Hz
AVG_LEN       = 400       # samples
THRESHOLD     =   0.1
CHAR_DIT_MS   =  60       # ms
FARN_DIT_MS   = 150       # ms

# ── SDR defaults ───────────────────────────────────────────────────────────────
DEFAULT_FREQ  = 14_025_000   # Hz  (20 m CW band)
DEFAULT_GAIN  = 30           # dB


# ── Flowgraph ──────────────────────────────────────────────────────────────────

class SDRFlowgraph(gr.top_block, Qt.QWidget):

    def __init__(self, freq=DEFAULT_FREQ, gain=DEFAULT_GAIN, ppm=0, sdr_args=''):
        gr.top_block.__init__(self, 'CW Decoder – SDR')
        Qt.QWidget.__init__(self)
        self.setWindowTitle('CW Morse Decoder — SDR')

        self._build_gui(freq, gain)
        self._build_flowgraph(freq, gain, ppm, sdr_args)

    # ── GUI ────────────────────────────────────────────────────────────────────

    def _build_gui(self, freq, gain):
        layout = Qt.QVBoxLayout(self)

        # Frequency row
        freq_row = Qt.QHBoxLayout()
        freq_row.addWidget(Qt.QLabel('Frequency (MHz):'))
        self._freq_spin = Qt.QDoubleSpinBox()
        self._freq_spin.setDecimals(4)
        self._freq_spin.setRange(0.1, 6000.0)
        self._freq_spin.setSingleStep(0.001)
        self._freq_spin.setValue(freq / 1e6)
        self._freq_spin.valueChanged.connect(self._on_freq_changed)
        freq_row.addWidget(self._freq_spin)
        layout.addLayout(freq_row)

        # Gain row
        gain_row = Qt.QHBoxLayout()
        gain_row.addWidget(Qt.QLabel('Gain (dB):'))
        self._gain_slider = Qt.QSlider(Qt.Qt.Horizontal)
        self._gain_slider.setRange(0, 50)
        self._gain_slider.setValue(gain)
        self._gain_label = Qt.QLabel(f'{gain} dB')
        self._gain_slider.valueChanged.connect(self._on_gain_changed)
        gain_row.addWidget(self._gain_slider)
        gain_row.addWidget(self._gain_label)
        layout.addLayout(gain_row)

        self._cw_widget = CWDecoderWidget()
        layout.addWidget(self._cw_widget)

    def _on_freq_changed(self, mhz):
        hz = int(mhz * 1e6)
        self.sdr_src.set_center_freq(hz)
        self._cw_widget.set_status(f'Tuned: {mhz:.4f} MHz')

    def _on_gain_changed(self, db):
        self._gain_label.setText(f'{db} dB')
        self.sdr_src.set_gain(db)

    # ── Flowgraph ──────────────────────────────────────────────────────────────

    def _build_flowgraph(self, freq, gain, ppm, sdr_args):
        decim = SDR_RATE // AUDIO_RATE   # integer decimation factor

        # 1. SDR source (IQ, complex64)
        self.sdr_src = osmosdr.source(args=sdr_args)
        self.sdr_src.set_sample_rate(SDR_RATE)
        self.sdr_src.set_center_freq(freq)
        self.sdr_src.set_gain(gain)
        if ppm:
            self.sdr_src.set_freq_corr(ppm)

        # 2. Complex channel filter — narrows to ±CHAN_BW Hz and decimates
        chan_taps = firdes.low_pass(
            gain=1.0,
            sampling_freq=SDR_RATE,
            cutoff_freq=CHAN_BW,
            transition_width=CHAN_TRANS,
            window=firdes.WIN_HAMMING,
        )
        self.chan_filt = gr_filter.fir_filter_ccf(decim, chan_taps)

        # 3. Envelope detection: complex → magnitude (float at AUDIO_RATE)
        self.c2mag = blocks.complex_to_mag()

        # 4. CW signal-conditioning pipeline
        self.pipeline = CWSignalPipeline(
            sample_rate=AUDIO_RATE,
            lpf_cutoff=LPF_CUTOFF,
            lpf_trans=LPF_TRANS,
            avg_len=AVG_LEN,
            threshold=THRESHOLD,
            char_dit_ms=CHAR_DIT_MS,
            farn_dit_ms=FARN_DIT_MS,
        )

        # Wire: SDR → channel filter → magnitude → CW pipeline
        self.connect(self.sdr_src, self.chan_filt, self.c2mag)
        self.pipeline.connect_source(self, self.c2mag)

        # Message sink → GUI
        self.msg_sink = qtgui.msg_sink(
            filter=pmt.PMT_NIL,
            msghandler=self._cw_widget.on_message,
            preserve_pmt=False,
        )
        self.msg_connect((self.pipeline.cw, 'decoded'), (self.msg_sink, 'in'))

        self._cw_widget.set_status(f'Tuned: {freq / 1e6:.4f} MHz')


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='CW Morse Decoder — SDR frontend',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('--freq', '-f', type=float, default=DEFAULT_FREQ,
                        metavar='HZ',
                        help=f'Carrier frequency in Hz (default: {DEFAULT_FREQ})')
    parser.add_argument('--gain', '-g', type=int, default=DEFAULT_GAIN,
                        metavar='DB',
                        help=f'SDR gain in dB (default: {DEFAULT_GAIN})')
    parser.add_argument('--ppm', type=int, default=0,
                        help='Frequency correction in PPM (default: 0)')
    parser.add_argument('--args', '-a', default='', metavar='ARGS',
                        help='osmosdr device args (e.g. "rtl=0" or "hackrf=0")')
    args = parser.parse_args()

    app = Qt.QApplication(sys.argv)
    tb  = SDRFlowgraph(
        freq=int(args.freq),
        gain=args.gain,
        ppm=args.ppm,
        sdr_args=args.args,
    )
    tb.start()
    tb.show()

    print(f'CW decoder running.  SDR tuned to {args.freq / 1e6:.4f} MHz.')
    print()

    try:
        app.exec_()
    except KeyboardInterrupt:
        pass
    finally:
        tb.stop()
        tb.wait()
        print('\nDecoder stopped.')


if __name__ == '__main__':
    main()
```

Now three files exist:

| File | Role |
|---|---|
| [`cw_decoder.py`](cw_decoder.py) | Module — decoder logic + `CWSignalPipeline` + `CWDecoderWidget` |
| [`frontend_audio.py`](frontend_audio.py) | Audio source or WAV file |
| [`frontend_sdr.py`](frontend_sdr.py) | RTL-SDR / osmosdr with live tuning |

**Audio frontend usage:**
```
python frontend_audio.py                     # system default input
python frontend_audio.py --device hw:1,0     # named device
python frontend_audio.py --file cw.wav       # WAV file
python frontend_audio.py --list-devices      # needs pip install sounddevice
```

**SDR frontend usage:**
```
python frontend_sdr.py --freq 14.025e6
python frontend_sdr.py --freq 7.030e6 --gain 40 --ppm -3
python frontend_sdr.py --freq 14.025e6 --args "rtl=0"
```

The SDR pipeline is: `osmosdr → complex channel filter (decimate 250k→8k) → complex_to_mag → CWSignalPipeline`. Frequency and gain are adjustable live via spinbox/slider in the GUI.