FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt update && apt install -y \
    build-essential meson ninja-build sudo tzdata procps \
    bison flex curl pkg-config cmake llvm clang \
    git vim unzip zstd default-jre \
    libicu-dev libreadline-dev libssl-dev libzstd-dev liblz4-dev libossp-uuid-dev liburing-dev \
    gdb gdbserver \
    && rm -rf /var/lib/apt/lists/*
RUN apt update && apt install -y python3-pip && rm -rf /var/lib/apt/lists/* \
    && pip3 install --no-cache-dir "meson>=1.10.1"
RUN useradd -m -s /bin/bash dev && echo "dev ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
USER dev
ENV CC=/usr/bin/gcc CXX=/usr/bin/g++
