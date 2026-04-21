#!/usr/bin/env bash
# Creates .venv with access to system-installed gnuradio, pmt, PyQt5, numpy.
set -e

python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo ""
echo "Done. Activate with:  source .venv/bin/activate"
