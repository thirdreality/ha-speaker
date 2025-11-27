#!/bin/bash

set -euo pipefail

INFO()  { echo -e "\e[1;32m[INFO]  $(date '+%Y-%m-%d %H:%M:%S')  $*\e[0m"; }
WARN()  { echo -e "\e[1;33m[WARN]  $(date '+%Y-%m-%d %H:%M:%S')  $*\e[0m" >&2; }
ERROR() { echo -e "\e[1;31m[ERROR] $(date '+%Y-%m-%d %H:%M:%S')  $*\e[0m" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDS_DIR="$SCRIPT_DIR/.pids"

PIPER_REPO="https://github.com/thirdreality/wyoming-piper.git"
WHISPER_REPO="https://github.com/thirdreality/wyoming-faster-whisper.git"
PIPER_DIR="$SCRIPT_DIR/wyoming-piper"
WHISPER_DIR="$SCRIPT_DIR/wyoming-faster-whisper"
BRANCH="ha-spk"

usage() {
    INFO "Usage: $0 {install|start|stop}"
    exit 1
}

check_dependencies() {
    INFO "Checking and installing dependencies..."
    sudo apt update -y
    sudo apt install -y python3-venv python3-pip git || {
        ERROR "Failed to install dependencies"
        exit 1
    }
}

clone_and_setup() {
    local repo_url="$1"
    local repo_dir="$2"
    local repo_name="$(basename "$repo_dir")"

    INFO "Setting up $repo_name..."

    if [ -d "$repo_dir" ]; then
        WARN "$repo_name already exists at $repo_dir"
        cd "$repo_dir"
        INFO "Fetching latest changes..."
        git fetch || { ERROR "Failed to fetch $repo_name"; exit 1; }
    else
        INFO "Cloning $repo_name from $repo_url"
        git clone "$repo_url" "$repo_dir" || {
            ERROR "Failed to clone $repo_name"
            exit 1
        }
        cd "$repo_dir"
    fi

    INFO "Checking out branch: $BRANCH"
    git checkout "$BRANCH" || {
        ERROR "Failed to checkout branch $BRANCH for $repo_name"
        exit 1
    }

    if [ -x "script/setup" ]; then
        INFO "Running setup for $repo_name"
        ./script/setup || {
            ERROR "Setup failed for $repo_name"
            exit 1
        }
    else
        ERROR "No executable setup script found for $repo_name"
        exit 1
    fi

    INFO "$repo_name setup completed successfully"
    cd "$SCRIPT_DIR"
}

install() {
    INFO "Installing Wyoming services to $SCRIPT_DIR"
    
    check_dependencies
    
    clone_and_setup "$PIPER_REPO" "$PIPER_DIR"
    clone_and_setup "$WHISPER_REPO" "$WHISPER_DIR"
    
    INFO "Installation completed successfully!"
}

start_piper() {
    if [ ! -d "$PIPER_DIR" ]; then
        ERROR "Piper directory not found at $PIPER_DIR. Run 'install' first."
        exit 1
    fi

    local data_dir="$PIPER_DIR/download"
    mkdir -p "$data_dir"

    INFO "Starting Wyoming Piper service..."
    cd "$PIPER_DIR"
    
    ./script/run \
        --voice 'en_US-lessac-medium' \
        --uri 'tcp://0.0.0.0:10200' \
        --data-dir "$data_dir" \
        --download-dir "$data_dir" &
    
    local pid=$!
    echo "$pid" > "$PIDS_DIR/piper.pid"
    INFO "Piper started (PID: $pid)"
    
    cd "$SCRIPT_DIR"
}

start_whisper() {
    if [ ! -d "$WHISPER_DIR" ]; then
        ERROR "Whisper directory not found at $WHISPER_DIR. Run 'install' first."
        exit 1
    fi

    local data_dir="$WHISPER_DIR/download"
    mkdir -p "$data_dir"

    INFO "Starting Wyoming Faster Whisper service..."
    cd "$WHISPER_DIR"
    
    ./script/run \
        --model tiny-int8 \
        --language en \
        --uri 'tcp://0.0.0.0:10300' \
        --data-dir "$data_dir" \
        --download-dir "$data_dir" &
    
    local pid=$!
    echo "$pid" > "$PIDS_DIR/whisper.pid"
    INFO "Whisper started (PID: $pid)"
    
    cd "$SCRIPT_DIR"
}

start() {
    mkdir -p "$PIDS_DIR"
    
    if [ -f "$PIDS_DIR/piper.pid" ]; then
        local pid=$(cat "$PIDS_DIR/piper.pid")
        if kill -0 "$pid" 2>/dev/null; then
            WARN "Piper is already running (PID: $pid)"
        else
            start_piper
        fi
    else
        start_piper
    fi
    
    sleep 1
    
    if [ -f "$PIDS_DIR/whisper.pid" ]; then
        local pid=$(cat "$PIDS_DIR/whisper.pid")
        if kill -0 "$pid" 2>/dev/null; then
            WARN "Whisper is already running (PID: $pid)"
        else
            start_whisper
        fi
    else
        start_whisper
    fi
    
    INFO "All services started successfully!"
}

stop() {
    INFO "Stopping Wyoming services..."
    
    local stopped=0
    
    if [ -f "$PIDS_DIR/piper.pid" ]; then
        local pid=$(cat "$PIDS_DIR/piper.pid")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" && INFO "Stopped Piper (PID: $pid)"
            stopped=$((stopped + 1))
        fi
        rm -f "$PIDS_DIR/piper.pid"
    fi
    
    if [ -f "$PIDS_DIR/whisper.pid" ]; then
        local pid=$(cat "$PIDS_DIR/whisper.pid")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" && INFO "Stopped Whisper (PID: $pid)"
            stopped=$((stopped + 1))
        fi
        rm -f "$PIDS_DIR/whisper.pid"
    fi
    
    if pgrep -f "python3 -m wyoming_" > /dev/null; then
        WARN "Found orphaned Wyoming processes, cleaning up..."
        pkill -f "python3 -m wyoming_"
    fi
    
    if [ $stopped -eq 0 ]; then
        WARN "No services were running"
    else
        INFO "Stopped $stopped service(s)"
    fi
}

if [ $# -eq 0 ]; then
    usage
fi

case "$1" in
    install)
        install
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    *)
        usage
        ;;
esac