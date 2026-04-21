"""
CW Morse Decoder — core module
==============================
Provides:
  MorseDecoder       – Morse symbol → character lookup tree
  TimingAnalyzer     – Classifies pulse/silence durations as dit/dah/space
  EdgeDetector       – Converts binary sample stream to timing events
  CWDecoderBlock     – GnuRadio sync_block: binary float stream → PMT messages
  CWSignalPipeline   – Builds the GR signal-conditioning chain
                       (LPF → square → IIR avg → threshold → CWDecoderBlock)
  CWDecoderWidget    – Qt widget: scrolling decoded-text display + Clear button
"""

import sys
import numpy as np
from PyQt5 import Qt


# ── Morse decode tree ──────────────────────────────────────────────────────────

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
            '.-.-.-': '.', '--..--': ',', '..--..': '?', '-..-.': '/',
            '-....-': '-', '-.--.': '(',  '-.--.-': ')',
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


# ── Timing analysis (Farnsworth-aware) ────────────────────────────────────────

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


# ── Edge detector ──────────────────────────────────────────────────────────────

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

    def flush(self):
        """Flush any pending tone as if an inter-character silence followed."""
        if self.last_value == 1:
            duration_ms = (self.run_length / self.sample_rate) * 1000
            self.timing.push_pulse(duration_ms)
        # 4× farn_dit_ms: always a letter gap (> char_dit_ms*2, < farn_dit_ms*5)
        return self.timing.push_silence(self.timing.farn_dit_ms * 4)


# ── GnuRadio CW decoder block ──────────────────────────────────────────────────

class CWDecoderBlock:
    """
    GnuRadio sync block.
    Input:  float32 binary stream (0.0 / 1.0) from threshold block.
    Output: PMT messages on 'decoded' port (one string per character).
            Also echoes decoded text to stdout for debugging.
    """

    def __init__(self, sample_rate=8000, char_dit_ms=60, farn_dit_ms=150):
        import pmt
        from gnuradio import gr
        gr.sync_block.__init__(self,
            name='CW Decoder',
            in_sig=[np.float32],
            out_sig=None)

        self._pmt   = pmt
        self.edge   = EdgeDetector(sample_rate, char_dit_ms, farn_dit_ms)
        self.morse  = MorseDecoder()

        self.message_port_register_out(pmt.intern('decoded'))

    def _emit(self, text):
        sys.stdout.write(text)
        sys.stdout.flush()
        self.message_port_pub(self._pmt.intern('decoded'), self._pmt.intern(text))

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


# ── Signal conditioning pipeline ───────────────────────────────────────────────

class CWSignalPipeline:
    """
    Builds and connects the GR blocks that condition a float audio signal
    for CW decoding.  Not itself a GR block — call connect_source() once the
    top block and this object have both been created.

    Pipeline:  LPF → square → IIR avg → threshold → CWDecoderBlock

    Parameters
    ----------
    sample_rate  : Hz  — must match the upstream audio/SDR decimated rate
    lpf_cutoff   : Hz  — low-pass cutoff to isolate the envelope band
    lpf_trans    : Hz  — LPF transition width
    avg_len      : samples — IIR smoothing window (2/avg_len → alpha)
    threshold    : 0–1 — envelope level for key-on/off decision
    char_dit_ms  : ms  — dit length at character speed
    farn_dit_ms  : ms  — dit length for inter-character gaps (Farnsworth)

    Attributes
    ----------
    cw : CWDecoderBlock
        Use for message-port connections: (pipeline.cw, 'decoded')
    """

    def __init__(self, sample_rate=8000,
                 lpf_cutoff=150, lpf_trans=50,
                 avg_len=400, threshold=0.1,
                 char_dit_ms=60, farn_dit_ms=150):
        from gnuradio import filter, blocks
        from gnuradio.filter import firdes

        lpf_taps = firdes.low_pass(
            gain=1.0,
            sampling_freq=sample_rate,
            cutoff_freq=lpf_cutoff,
            transition_width=lpf_trans,
            window=firdes.WIN_HAMMING,
        )
        self.lpf    = filter.fir_filter_fff(1, lpf_taps)
        self.sqr    = blocks.multiply_ff()
        self.avg    = filter.single_pole_iir_filter_ff(2.0 / avg_len)
        self.thresh = blocks.threshold_ff(
            lo=threshold * 0.8,
            hi=threshold,
            initial_state=0,
        )
        self.cw = CWDecoderBlock(sample_rate, char_dit_ms, farn_dit_ms)

    def connect_source(self, tb, source):
        """Wire *source* (a single-output float32 block) into this pipeline."""
        tb.connect(source,     self.lpf)
        tb.connect(self.lpf,   (self.sqr, 0))
        tb.connect(self.lpf,   (self.sqr, 1))
        tb.connect(self.sqr,   self.avg)
        tb.connect(self.avg,   self.thresh)
        tb.connect(self.thresh, self.cw)


# ── Qt display widget ──────────────────────────────────────────────────────────

class CWDecoderWidget(Qt.QWidget):
    """
    Scrolling decoded-text display with a status line and Clear button.

    Connect to a CWDecoderBlock via on_message(), typically through a
    qtgui.msg_sink msghandler callback.
    """

    def __init__(self, parent=None):
        import pmt as _pmt
        self._pmt = _pmt
        super().__init__(parent)
        layout = Qt.QVBoxLayout(self)

        layout.addWidget(Qt.QLabel('Decoded text:'))

        self._text_box = Qt.QTextEdit()
        self._text_box.setReadOnly(True)
        self._text_box.setMinimumHeight(200)
        self._text_box.setStyleSheet('font-family: monospace; font-size: 16pt;')
        layout.addWidget(self._text_box)

        row = Qt.QHBoxLayout()
        self._status = Qt.QLabel('Listening…')
        row.addWidget(self._status)
        clear_btn = Qt.QPushButton('Clear')
        clear_btn.clicked.connect(self._text_box.clear)
        row.addWidget(clear_btn)
        layout.addLayout(row)

    def set_status(self, text):
        self._status.setText(text)

    def on_message(self, msg):
        """Append a decoded PMT symbol string and auto-scroll."""
        text = self._pmt.symbol_to_string(msg)
        self._text_box.insertPlainText(text)
        sb = self._text_box.verticalScrollBar()
        sb.setValue(sb.maximum())
