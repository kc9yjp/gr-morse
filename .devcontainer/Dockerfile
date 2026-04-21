FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    gnuradio \
    gr-osmosdr \
    python3-pyqt5 \
    python3-numpy \
    rtl-sdr \
    xauth \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages sounddevice pytest
