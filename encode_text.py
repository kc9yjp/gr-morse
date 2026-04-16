"""
CW Encoder — GUI or CLI frontend
=================================
With no arguments, opens a GUI.  When --text or piped stdin is provided,
encodes without a GUI and writes directly to a WAV file.

Usage
-----
  python encode_text.py                          # GUI mode
  python encode_text.py --text "CQ CQ DE W1AW"  # CLI, single message
  echo "CQ CQ" | python encode_text.py          # CLI, stdin
  python encode_text.py --text "HI" --wpm 25 --farn 15 --tone 600 --out hi.wav
"""

import argparse
import sys

from cw_encoder import CWAudioEncoder

# ── Defaults ───────────────────────────────────────────────────────────────────
CHAR_WPM    = 20
FARN_WPM    = 20
TONE_HZ     = 700
SAMPLE_RATE = 8_000
OUTPUT_FILE = 'output.wav'


def encode_cli(text, char_wpm, farn_wpm, tone_hz, sample_rate, outfile):
    enc = CWAudioEncoder(
        char_wpm=char_wpm,
        farn_wpm=farn_wpm,
        tone_hz=tone_hz,
        sample_rate=sample_rate,
    )
    samples = enc.encode(text)
    enc.write_wav(samples, outfile)
    duration_s = len(samples) / sample_rate
    print(f'Saved: {outfile}  ({duration_s:.1f} s @ {char_wpm} WPM / '
          f'{farn_wpm} WPM Farnsworth / {tone_hz} Hz)')


# ── GUI ────────────────────────────────────────────────────────────────────────

def run_gui(defaults):
    from PyQt5 import Qt

    class EncoderWindow(Qt.QWidget):

        def __init__(self):
            super().__init__()
            self.setWindowTitle('CW Morse Encoder')
            layout = Qt.QVBoxLayout(self)

            layout.addWidget(Qt.QLabel('Text to encode:'))
            self._text = Qt.QTextEdit()
            self._text.setPlaceholderText('Enter text here…')
            self._text.setMinimumHeight(120)
            self._text.setStyleSheet('font-family: monospace; font-size: 14pt;')
            layout.addWidget(self._text)

            params = Qt.QFormLayout()

            self._wpm = Qt.QSpinBox()
            self._wpm.setRange(5, 60)
            self._wpm.setValue(defaults['char_wpm'])
            self._wpm.setSuffix(' WPM')
            self._wpm.valueChanged.connect(self._clamp_farn)
            params.addRow('Character speed:', self._wpm)

            self._farn = Qt.QSpinBox()
            self._farn.setRange(5, 60)
            self._farn.setValue(defaults['farn_wpm'])
            self._farn.setSuffix(' WPM')
            params.addRow('Farnsworth speed (≤ char):', self._farn)

            self._tone = Qt.QSpinBox()
            self._tone.setRange(200, 1500)
            self._tone.setValue(defaults['tone_hz'])
            self._tone.setSuffix(' Hz')
            params.addRow('Tone frequency:', self._tone)

            layout.addLayout(params)

            file_container = Qt.QWidget()
            file_row = Qt.QHBoxLayout(file_container)
            file_row.setContentsMargins(0, 0, 0, 0)
            self._outfile = Qt.QLineEdit(defaults['outfile'])
            file_row.addWidget(self._outfile)
            browse_btn = Qt.QPushButton('Browse…')
            browse_btn.clicked.connect(self._browse)
            file_row.addWidget(browse_btn)
            file_form = Qt.QFormLayout()
            file_form.addRow('Output file:', file_container)
            layout.addLayout(file_form)

            self._encode_btn = Qt.QPushButton('Encode')
            self._encode_btn.clicked.connect(self._encode)
            layout.addWidget(self._encode_btn)

            self._status = Qt.QLabel('Ready.')
            layout.addWidget(self._status)

        def _clamp_farn(self, char_wpm):
            if self._farn.value() > char_wpm:
                self._farn.setValue(char_wpm)

        def _browse(self):
            path, _ = Qt.QFileDialog.getSaveFileName(
                self, 'Save WAV file', self._outfile.text(), 'WAV files (*.wav)'
            )
            if path:
                self._outfile.setText(path)

        def _encode(self):
            text = self._text.toPlainText().strip()
            if not text:
                self._status.setText('No text to encode.')
                return
            outfile = self._outfile.text().strip()
            if not outfile:
                self._status.setText('No output file specified.')
                return

            self._status.setText('Encoding…')
            self._encode_btn.setEnabled(False)
            Qt.QApplication.processEvents()

            try:
                encode_cli(
                    text,
                    char_wpm=self._wpm.value(),
                    farn_wpm=self._farn.value(),
                    tone_hz=self._tone.value(),
                    sample_rate=defaults['sample_rate'],
                    outfile=outfile,
                )
                duration_s = 0  # already printed by encode_cli
                self._status.setText(f'Saved: {outfile}')
            except Exception as e:
                self._status.setText(f'Error: {e}')
            finally:
                self._encode_btn.setEnabled(True)

    app = Qt.QApplication(sys.argv)
    win = EncoderWindow()
    win.resize(520, 440)
    win.show()
    sys.exit(app.exec_())


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Encode text to Morse code WAV. Omit --text and stdin for GUI mode.'
    )
    parser.add_argument('--text', '-t', help='Text to encode (CLI mode)')
    parser.add_argument('--wpm', type=int, default=CHAR_WPM,
                        help=f'Character speed in WPM (default: {CHAR_WPM})')
    parser.add_argument('--farn', type=int, default=None,
                        help='Farnsworth spacing speed in WPM (default: same as --wpm)')
    parser.add_argument('--tone', type=int, default=TONE_HZ,
                        help=f'Sidetone frequency in Hz (default: {TONE_HZ})')
    parser.add_argument('--rate', type=int, default=SAMPLE_RATE,
                        help=f'Sample rate in Hz (default: {SAMPLE_RATE})')
    parser.add_argument('--out', '-o', default=OUTPUT_FILE,
                        help=f'Output WAV file (default: {OUTPUT_FILE})')
    args = parser.parse_args()

    farn_wpm = args.farn if args.farn is not None else args.wpm

    # Determine text: explicit arg > stdin pipe > GUI
    text = None
    if args.text:
        text = args.text
    elif not sys.stdin.isatty():
        text = sys.stdin.read().strip()

    if text:
        if farn_wpm > args.wpm:
            parser.error('--farn must be ≤ --wpm')
        encode_cli(text, args.wpm, farn_wpm, args.tone, args.rate, args.out)
    else:
        run_gui({
            'char_wpm': args.wpm,
            'farn_wpm': farn_wpm,
            'tone_hz': args.tone,
            'sample_rate': args.rate,
            'outfile': args.out,
        })


if __name__ == '__main__':
    main()
