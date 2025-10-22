#!/bin/bash

set -e
trap 'ERROR "Build failed at line $LINENO."' ERR

INFO()  { echo -e "\e[1;32m[INFO]    $1\e[0m"; }
ERROR() { echo -e "\e[1;31m[ERROR]   $1\e[0m" >&2; exit 1; }

if [ -z "$1" ]; then
    ERROR "Missing target name! Usage: $0 <target_name>"
fi

ROOT_DIR=$(pwd)
BUILDROOT_DIR="${ROOT_DIR}/buildroot"
BUILD_OUTPUT_DIR="${ROOT_DIR}/output"
TARGET_BUILD_CONFIG="3reality_${1}_release"
TARGET_OUTPUT_DIR="${BUILD_OUTPUT_DIR}/${TARGET_BUILD_CONFIG}"
TOOLCHAIN_DIR="${ROOT_DIR}/sources/toolchain"
IMAGE_DIR="${ROOT_DIR}/image"

TOOLCHAINS=(
    "${TOOLCHAIN_DIR}/CodeSourcery/Sourcery_G++_Lite/bin"
    "${TOOLCHAIN_DIR}/gcc-linaro-7.5.0-2019.12-x86_64_aarch64-elf/bin"
)

for tc in "${TOOLCHAINS[@]}"; do
    if [ -d "${tc}" ]; then
        if [[ ":${PATH}:" != *":${tc}:"* ]]; then
            export PATH="${tc}:${PATH}"
            # INFO "Added to PATH: $tc"
        fi
    else
        ERROR "Toolchain directory not found: ${tc}"
    fi
done

mkdir -p ${TARGET_OUTPUT_DIR}
cd ${BUILDROOT_DIR}

INFO "Starting build for ${TARGET_BUILD_CONFIG}..."
make O="${TARGET_OUTPUT_DIR}" ${TARGET_BUILD_CONFIG}_defconfig
make O="${TARGET_OUTPUT_DIR}"

INFO "Build completed successfully!"
mkdir -p "${IMAGE_DIR}"
cp -rf ${TARGET_OUTPUT_DIR}/images/aml_upgrade_package.img ${ROOT_DIR}/image/${1}.img
