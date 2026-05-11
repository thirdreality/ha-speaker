FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN dpkg --add-architecture i386 \
    && apt-get update && apt-get install -y \
    build-essential bash bc binutils bzip2 cpio g++ gcc git gzip \
    locales libncurses5-dev libdevmapper-dev libsystemd-dev make \
    mercurial whois patch perl python rsync sed tar vim unzip wget \
    bison flex libssl-dev \
    libc6:i386 libncurses5:i386 libstdc++6:i386 zlib1g-dev:i386 \
    zip python3-pip pkg-config automake gsettings-ubuntu-schemas \
    libglib2.0-dev gcc-multilib g++-multilib jq \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pycrypto

RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8

# U-Boot Makefile hardcodes these absolute paths for CROSS_COMPILE
# Create symlinks pointing to the toolchains in sources/toolchain (mounted at /build)
RUN mkdir -p /opt/CodeSourcery && \
    ln -sf /build/sources/toolchain/gcc-linaro-7.5.0-2019.12-x86_64_aarch64-elf /opt/gcc-linaro-7.3.1-2018.05-i686_aarch64-elf && \
    ln -sf /build/sources/toolchain/CodeSourcery/Sourcery_G++_Lite /opt/CodeSourcery/Sourcery_G++_Lite

WORKDIR /build

ENTRYPOINT ["./go"]
CMD ["trspk"]
