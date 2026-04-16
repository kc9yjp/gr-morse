#!/usr/bin/env python3
"""
CW Morse Code Decoder - GnuRadio Flowgraph
==========================================
Pipeline:
  Audio Source (soundcard or SDR)
    -> Low Pass Filter       (isolate CW tone band)
    -> Complex to Mag        (envelope)
    -> Moving Average        (smooth envelope)
    -> Threshold             (binary 0/1)
    -> CW Decoder block      (EdgeDetector + TimingAnalyzer + MorseDecoder)
    -> Message port          -> qtgui text sink  (GUI)
                             -> console print    (debug)

Dependencies:
    pip install gnuradio
    (gr-qtgui is included with most GnuRadio installs)

Usage:
    python cw_decoder.py
"""

import sys
import time
import numpy as np
import pmt

from gnuradio import gr, audio, filter, blocks, qtgui
from gnuradio.filter import firdes
from PyQt5 import Qt


# ---------------------------------------------------------------------------
# Morse decode tree
# ---------------------------------------------------------------------------

class MorseNode:
    def __init__(self):
        self.letter = ''
        self.dit = None
        self.dah = None


class MorseDecoder:
    def __init__(self):
        self.root = MorseNode()
        self._build_tree()

    def _insert(self, sequence, letter):
        node = self.root
        for symbol in sequence:
            if symbol == '.':
                if node.dit is None:
                    node.dit = MorseNode()
                node = node.dit
            elif symbol == '-':
                if node.dah is None:
                    node.dah = MorseNode()
                node = node.dah
        node.letter = letter

    def _build_tree(self):
        codes = {
            '.':    'E',  '-':    'T',
            '..':   'I',  '.-':   'A',  '-.':   'N',  '--':   'M',
            '...':  'S',  '..-':  'U',  '.-.':  'R',  '.--':  'W',
            '-..':  'D',  '-.-':  'K',  '--.':  'G',  '---':  'O',
            '....': 'H',  '...-': 'V',  '..-.': 'F',
            '.-..': 'L',  '.--.' : 'P',  '.---': 'J',
            '-...': 'B',  '-..-': 'X',  '-.-.': 'C',  '-.--': 'Y',
            '--..': 'Z',  '--.-': 'Q',
            '.----': '1', '..---': '2', '...--': '3', '....-': '4',
            '.....': '5', '-....': '6', '--...': '7', '---..': '8',
            '----.': '9', '-----': '0',
        }
        for seq, ch in codes.items():
            self._insert(seq, ch)

    def decode_symbol(self, sequence):
        node = self.root
        for symbol in sequence:
            if symbol == '.':
                node = node.dit
            elif symbol == '-':
                node = node.dah
            if node is None:
                return '?'
        return node.letter if node.letter else '?'


# ---------------------------------------------------------------------------
# Timing analysis (Farnsworth-aware)
# ---------------------------------------------------------------------------

class TimingAnalyzer:
    def __init__(self, char_dit_ms=60, farn_dit_ms=150):
        self.char_dit_ms = char_dit_ms
        self.farn_dit_ms = farn_dit_ms
        self._current_symbol = []

    def _classify_pulse(self, duration_ms):
        return '.' if duration_ms < self.char_dit_ms * 2 else '-'

    def _classify_silence(self, duration_ms):
        if duration_ms < self.char_dit_ms * 2:
            return 'intra'
        elif duration_ms < self.farn_dit_ms * 5:
            return 'letter'
        return 'word'

    def push_pulse(self, duration_ms):
        self._current_symbol.append(self._classify_pulse(duration_ms))

    def push_silence(self, duration_ms):
        kind = self._classify_silence(duration_ms)
        if kind == 'intra':
            return ('intra', None)
        symbol = ''.join(self._current_symbol)
        self._current_symbol = []
        return (kind, symbol if symbol else None)


# ---------------------------------------------------------------------------
# Edge detector  (binary sample stream -> pulse/silence durations)
# ---------------------------------------------------------------------------

class EdgeDetector:
    def __init__(self, sample_rate=8000, char_dit_ms=60, farn_dit_ms=150):
        self.sample_rate = sample_rate
        self.timing = TimingAnalyzer(char_dit_ms, farn_dit_ms)
        self.last_value = 0
        self.run_length = 0

    def push_sample(self, value):
        binary = 1 if value > 0.5 else 0
        if binary == self.last_value:
            self.run_length += 1
            return None

        duration_ms = (self.run_length / self.sample_rate) * 1000

        if self.last_value == 1:
            self.timing.push_pulse(duration_ms)
            result = None
        else:
            result = self.timing.push_silence(duration_ms)

        self.last_value = binary
        self.run_length = 1
        return result


# ---------------------------------------------------------------------------
# GnuRadio block — wires EdgeDetector + MorseDecoder, emits messages
# ---------------------------------------------------------------------------

class CWDecoderBlock(gr.sync_block):
    """
    GnuRadio sync block.
    Input:  float32 binary stream (0.0 / 1.0) from threshold block
    Output: PMT messages on 'decoded' port (one per character)
            Also prints decoded text to stdout for debugging.
    """

    def __init__(self, sample_rate=8000, char_dit_ms=60, farn_dit_ms=150):
        gr.sync_block.__init__(self,
            name='CW Decoder',
            in_sig=[np.float32],
            out_sig=None)

        self.edge  = EdgeDetector(sample_rate, char_dit_ms, farn_dit_ms)
        self.morse = MorseDecoder()

        self.message_port_register_out(pmt.intern('decoded'))

    def _emit(self, text):
        """Send text to both the message port (GUI) and stdout (debug)."""
        sys.stdout.write(text)
        sys.stdout.flush()
        self.message_port_pub(pmt.intern('decoded'), pmt.intern(text))

    def work(self, input_items, output_items):
        for sample in input_items[0]:
            result = self.edge.push_sample(sample)

            if result is None:
                continue

            kind, symbol = result

            if kind == 'intra' or symbol is None:
                continue

            letter = self.morse.decode_symbol(symbol)

            if kind == 'word':
                self._emit(letter)
                self._emit(' ')
            else:
                self._emit(letter)

        return len(input_items[0])


# ---------------------------------------------------------------------------
# Top-level flowgraph
# ---------------------------------------------------------------------------

class CWFlowgraph(gr.top_block, Qt.QWidget):
    """
    Full GnuRadio flowgraph:
      audio source -> LPF -> envelope -> moving avg -> threshold -> CW decoder -> GUI
    
    Tune AUDIO_FREQ to the CW tone coming out of your receiver (typically 600-800 Hz).
    Tune CHAR_DIT_MS / FARN_DIT_MS to match the sender's speed.
    """

    SAMPLE_RATE  = 8000     # Hz  — audio sample rate
    AUDIO_FREQ   = 700      # Hz  — expected CW tone frequency
    LPF_CUTOFF   = 150      # Hz  — low pass filter cutoff (half the CW passband)
    LPF_TRANS    = 50       # Hz  — LPF transition width
    AVG_LEN      = 400      # samples — moving average window (~50ms at 8kHz)
    THRESHOLD    = 0.1      # 0.0-1.0 — envelope threshold for on/off decision
    CHAR_DIT_MS  = 60       # ms  — dit length at character speed (18 WPM)
    FARN_DIT_MS  = 150      # ms  — dit length for inter-char gaps (Farnsworth)

    def __init__(self):
        gr.top_block.__init__(self, 'CW Decoder')
        Qt.QWidget.__init__(self)
        self.setWindowTitle('CW Morse Decoder')

        # --- Build the Qt layout ---
        self._layout = Qt.QVBoxLayout(self)

        self._label = Qt.QLabel('Decoded text:')
        self._layout.addWidget(self._label)

        self._text_box = Qt.QTextEdit()
        self._text_box.setReadOnly(True)
        self._text_box.setMinimumHeight(200)
        self._text_box.setStyleSheet('font-family: monospace; font-size: 16pt;')
        self._layout.addWidget(self._text_box)

        status_row = Qt.QHBoxLayout()
        self._status = Qt.QLabel('Listening...')
        status_row.addWidget(self._status)

        self._clear_btn = Qt.QPushButton('Clear')
        self._clear_btn.clicked.connect(self._text_box.clear)
        status_row.addWidget(self._clear_btn)
        self._layout.addLayout(status_row)

        # --- GnuRadio blocks ---

        # 1. Audio source (system soundcard, mono)
        self.audio_src = audio.source(self.SAMPLE_RATE, '', True)

        # 2. Low pass filter — isolates the CW tone band
        lpf_taps = firdes.low_pass(
            gain=1.0,
            sampling_freq=self.SAMPLE_RATE,
            cutoff_freq=self.LPF_CUTOFF,
            transition_width=self.LPF_TRANS,
            window=firdes.WIN_HAMMING
        )
        self.lpf = filter.fir_filter_fff(1, lpf_taps)

        # 3. Complex to magnitude — rectify to get the envelope
        #    (audio is already real, so we use multiply to self as a simple rectifier)
        self.sqr = blocks.multiply_ff()

        # 4. Moving average — smooths the squared envelope
        self.avg = filter.single_pole_iir_filter_ff(
            2.0 / self.AVG_LEN
        )

        # 5. Threshold — binary on/off
        self.thresh = blocks.threshold_ff(
            lo=self.THRESHOLD * 0.8,
            hi=self.THRESHOLD,
            initial_state=0
        )

        # 6. CW decoder block
        self.cw = CWDecoderBlock(
            sample_rate=self.SAMPLE_RATE,
            char_dit_ms=self.CHAR_DIT_MS,
            farn_dit_ms=self.FARN_DIT_MS
        )

        # 7. qtgui message sink — receives PMT messages from cw block
        self.msg_sink = qtgui.msg_sink(
            filter=pmt.PMT_NIL,
            msghandler=self._on_message,
            preserve_pmt=False
        )

        # --- Wire the flowgraph ---
        self.connect(self.audio_src, self.lpf)
        self.connect(self.lpf, (self.sqr, 0))
        self.connect(self.lpf, (self.sqr, 1))   # multiply signal by itself -> square
        self.connect(self.sqr, self.avg)
        self.connect(self.avg, self.thresh)
        self.connect(self.thresh, self.cw)

        self.msg_connect((self.cw, 'decoded'), (self.msg_sink, 'in'))

    def _on_message(self, msg):
        """Called by qtgui msg_sink when a decoded character arrives."""
        text = pmt.symbol_to_string(msg)
        self._text_box.insertPlainText(text)
        # Auto-scroll to bottom
        sb = self._text_box.verticalScrollBar()
        sb.setValue(sb.maximum())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = Qt.QApplication(sys.argv)

    tb = CWFlowgraph()
    tb.start()
    tb.show()

    print('CW decoder running. Listening on default audio input.')
    print('Tune your receiver to a CW signal and watch characters appear.\n')

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
