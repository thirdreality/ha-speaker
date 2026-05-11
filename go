#!/bin/bash

# set -e
trap 'ERROR "Build failed at line $LINENO."' ERR

INFO()  { echo -e "\e[1;32m[INFO]    $1\e[0m"; }
ERROR() { echo -e "\e[1;31m[ERROR]   $1\e[0m" >&2; exit 1; }

usage() {
    cat <<EOF
Usage:
  ./go <target> [version]              Build natively
  ./go --docker <target> [version]     Build inside Docker container
  ./go --docker-shell                  Enter Docker container interactively
  ./go -h, --help                      Show this help message

Arguments:
  target      Build target name (e.g. trspk)
  version     Optional version string (default: date-based, e.g. 0.05.10)

Examples:
  ./go trspk                           Native build with date-based version
  ./go trspk 1.2.3                     Native build with version 1.2.3
  ./go --docker trspk                  Docker build (no host deps required)
  ./go --docker trspk 1.2.3            Docker build with version 1.2.3
  ./go --docker-shell                  Debug inside the build container

Output:
  image/<target>_<version>.img         Firmware image for USB burning
  image/<target>_<version>.swu         OTA update package
EOF
    exit 0
}

#--- Docker build mode ---#
docker_build() {
    local IMAGE_NAME="voice-music-assistant-builder"
    local ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"

    # Build Docker image if not exists, or rebuild if Dockerfile is newer
    local NEED_BUILD=false
    if ! docker image inspect "${IMAGE_NAME}" &>/dev/null; then
        NEED_BUILD=true
    else
        local IMAGE_CREATED
        IMAGE_CREATED=$(docker image inspect -f '{{.Created}}' "${IMAGE_NAME}" 2>/dev/null)
        local IMAGE_TS
        IMAGE_TS=$(date -d "${IMAGE_CREATED}" +%s 2>/dev/null || echo 0)
        local DOCKERFILE_TS
        DOCKERFILE_TS=$(stat -c %Y "${ROOT_DIR}/Dockerfile" 2>/dev/null || echo 0)
        if [ "${DOCKERFILE_TS}" -gt "${IMAGE_TS}" ]; then
            NEED_BUILD=true
        fi
    fi
    if [ "${NEED_BUILD}" = true ]; then
        INFO "Building Docker image..."
        docker build -t "${IMAGE_NAME}" "${ROOT_DIR}" || ERROR "Docker image build failed"
    fi

    local DOCKER_RUN_ARGS=(
        --rm
        -u "$(id -u):$(id -g)"
        -v "${ROOT_DIR}:/build"
        -e "HOME=/build"
    )

    # If buildroot/dl is a symlink, mount the real target so the container can access it
    local DL_PATH="${ROOT_DIR}/buildroot/dl"
    if [ -L "${DL_PATH}" ]; then
        local DL_REAL="$(readlink -f "${DL_PATH}")"
        DOCKER_RUN_ARGS+=(-v "${DL_REAL}:${DL_REAL}")
        DOCKER_RUN_ARGS+=(-v "${DL_REAL}:/build/buildroot/dl")
    fi

    if [ "$1" = "--shell" ]; then
        INFO "Starting interactive shell in Docker..."
        exec docker run -it "${DOCKER_RUN_ARGS[@]}" --entrypoint /bin/bash "${IMAGE_NAME}"
    else
        INFO "Starting Docker build: ./go $*"
        exec docker run "${DOCKER_RUN_ARGS[@]}" "${IMAGE_NAME}" "$@"
    fi
}

#--- Parse arguments ---#
case "$1" in
    --docker)
        shift
        [ -z "$1" ] && ERROR "Missing target name! Usage: ./go --docker <target> [version]"
        docker_build "$@"
        ;;
    --docker-shell)
        docker_build --shell
        ;;
    -h|--help|"")
        usage
        ;;
esac

ROOT_DIR=$(pwd)
BUILDROOT_DIR="${ROOT_DIR}/buildroot"
BUILD_OUTPUT_DIR="${ROOT_DIR}/output"
TARGET_BUILD_CONFIG="3reality_${1}"
TARGET_OUTPUT_DIR="${BUILD_OUTPUT_DIR}/${TARGET_BUILD_CONFIG}"
TOOLCHAIN_DIR="${ROOT_DIR}/sources/toolchain"
IMAGE_DIR="${ROOT_DIR}/image"
IMAGE_VERSION="${2}"
if [ -z "${IMAGE_VERSION}" ]; then
    IMAGE_VERSION=$(date "+0.%m.%d")
fi

# Check submodules are initialized
if [ ! -d "${TOOLCHAIN_DIR}/gcc-arm-10.2-2020.11-x86_64-aarch64-none-linux-gnu" ]; then
    ERROR "Toolchain submodule not initialized. Run: git submodule update --init"
fi

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
SPEAKER_FIRMWARE_VERSION="${IMAGE_VERSION}" make O="${TARGET_OUTPUT_DIR}"

INFO "Build completed successfully!"
mkdir -p "${IMAGE_DIR}"
cp -rf ${TARGET_OUTPUT_DIR}/images/aml_upgrade_package.img ${ROOT_DIR}/image/${1}_${IMAGE_VERSION}.img
cp -rf ${TARGET_OUTPUT_DIR}/images/software.swu ${ROOT_DIR}/image/${1}_${IMAGE_VERSION}.swu
