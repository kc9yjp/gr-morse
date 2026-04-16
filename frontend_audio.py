"""
CW Decoder — Audio frontend
===========================
Accepts either a live soundcard input or a WAV file.

Usage
-----
  python frontend_audio.py                          # system default mic/line-in
  python frontend_audio.py --device hw:1,0          # named ALSA/PortAudio device
  python frontend_audio.py --file recording.wav     # decode a WAV file
  python frontend_audio.py --list-devices           # print available devices and exit

WAV files are played back throttled to real-time so the pipeline timing is
preserved.  The file must be mono float32 or 16-bit PCM at any sample rate;
if the rate differs from SAMPLE_RATE the signal will be decoded at the file's
native rate (set SAMPLE_RATE below to match, or resample the file first).
"""

import argparse
import sys

from gnuradio import gr, audio, blocks, qtgui
import pmt
from PyQt5 import Qt

from cw_decoder import CWSignalPipeline, CWDecoderWidget

# ── Pipeline defaults (edit here or subclass) ──────────────────────────────────
SAMPLE_RATE  = 8_000   # Hz — audio sample rate
LPF_CUTOFF   = 150     # Hz — low-pass cutoff for envelope extraction
LPF_TRANS    = 50      # Hz — LPF transition width
AVG_LEN      = 400     # samples — IIR smoothing window (~50 ms at 8 kHz)
THRESHOLD    = 0.1     # 0–1 — envelope threshold for key on/off
CHAR_DIT_MS  = 60      # ms — dit length at character speed (~18 WPM)
FARN_DIT_MS  = 150     # ms — dit length for inter-char gaps (Farnsworth)


# ── Flowgraph ──────────────────────────────────────────────────────────────────

class AudioFlowgraph(gr.top_block, Qt.QWidget):

    def __init__(self, device='', wav_file=None):
        gr.top_block.__init__(self, 'CW Decoder – Audio')
        Qt.QWidget.__init__(self)
        self.setWindowTitle('CW Morse Decoder — Audio')

        self._cw_widget = CWDecoderWidget()
        layout = Qt.QVBoxLayout(self)
        layout.addWidget(self._cw_widget)

        pipeline = CWSignalPipeline(
            sample_rate=SAMPLE_RATE,
            lpf_cutoff=LPF_CUTOFF,
            lpf_trans=LPF_TRANS,
            avg_len=AVG_LEN,
            threshold=THRESHOLD,
            char_dit_ms=CHAR_DIT_MS,
            farn_dit_ms=FARN_DIT_MS,
        )

        if wav_file:
            self.src      = blocks.wavfile_source(wav_file, repeat=False)
            # throttle keeps wall-clock time correct for the decoder
            self.throttle = blocks.throttle(gr.sizeof_float, SAMPLE_RATE, True)
            self.connect((self.src, 0), self.throttle)
            pipeline.connect_source(self, self.throttle)
            self._cw_widget.set_status(f'File: {wav_file}')
        else:
            self.src = audio.source(SAMPLE_RATE, device, True)
            pipeline.connect_source(self, self.src)
            label = device if device else 'default audio input'
            self._cw_widget.set_status(f'Listening: {label}')

        self.msg_sink = qtgui.msg_sink(
            filter=pmt.PMT_NIL,
            msghandler=self._cw_widget.on_message,
            preserve_pmt=False,
        )
        self.msg_connect((pipeline.cw, 'decoded'), (self.msg_sink, 'in'))


# ── Device listing helper ──────────────────────────────────────────────────────

def list_devices():
    try:
        import sounddevice as sd
        print('Available input devices:')
        for idx, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] > 0:
                print(f"  [{idx:2d}] {dev['name']}")
    except ImportError:
        print('Install sounddevice (pip install sounddevice) to list devices.')
        print('Alternatively, use your OS audio settings to find device names.')


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='CW Morse Decoder — Audio frontend',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Usage')[0].strip(),
    )
    src_group = parser.add_mutually_exclusive_group()
    src_group.add_argument('--device', '-d', default='', metavar='NAME',
                           help='Audio input device name (default: system default)')
    src_group.add_argument('--file', '-f', metavar='WAV',
                           help='WAV file to decode instead of live audio')
    parser.add_argument('--list-devices', '-l', action='store_true',
                        help='List available audio input devices and exit')
    args = parser.parse_args()

    if args.list_devices:
        list_devices()
        return

    app = Qt.QApplication(sys.argv)
    tb  = AudioFlowgraph(device=args.device, wav_file=args.file)
    tb.start()
    tb.show()

    if args.file:
        print(f'CW decoder running.  Source: {args.file}')
    else:
        print(f'CW decoder running.  Source: {args.device or "default audio input"}')
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
