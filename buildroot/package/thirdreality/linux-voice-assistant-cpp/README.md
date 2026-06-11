# linux-voice-assistant-cpp

C++ rewrite of the `linux-voice-assistant` Buildroot package — full
replacement of the Python voice assistant. Design documented at
[`doc/linux-voice-assistant-cpp-refactor-plan.md`](../../../../doc/linux-voice-assistant-cpp-refactor-plan.md).

## Status: feature-complete (all phases done)

The binary is the production voice assistant. Python LVA packages have
been removed from the defconfig.

## Features

- ESPHome native API server (TCP 6053, plain-text framing, protobuf)
- 12 entities: mute switch, thinking-sound switch, 3× wake-word
  sensitivity numbers, mic gain, mic volume, mic noise select,
  media player, home button event, firmware update, check-for-updates
  button
- Voice satellite state machine (wake → STT stream → TTS playback →
  timer ring loop)
- MicroWakeWord inference (TFLM microfrontend + TFLite C runtime,
  dlopen)
- WebRTC AGC + noise suppression on mic input
- LED ring animations via D-Bus
- Home button monitor (/dev/input/event0, single/double/triple press)
- Mic mute GPIO bridge (hardware slider ↔ HA switch)
- ALSA system volume sync via adckey_function.sh
- Sendspin duck/unduck (SIGUSR1/2) during voice pipelines
- sound.json external-change watcher (500 ms poll)
- Supervisor HTTP API on port 8086 (HMAC-MD5 signed commands)
- OTA: check version, download, MD5 verify, swupdate install
- Timezone sync from HA (GetTimeRequest/GetTimeResponse)

## Build

```
./go --docker trspk rebuild linux-voice-assistant-cpp
```

Full image:
```
./go --docker trspk <version>
```

## Runtime invocation

Launched by `S99ha-speaker`:
```
/usr/bin/linux-voice-assistant-cpp \
    --name "$spk_name" \
    --port 6053
```

All options:
```
--name <name>            Device name (from device.json)
--port <port>            TCP port (default: 6053)
--host <addr>            Bind address (default: 0.0.0.0)
--preferences-file <p>   Prefs file (default: /data/conf/sound.json)
--audio-device <dev>     PulseAudio device (default: system default)
--wakeword-dir <dir>     Wake-word model dir (default: /usr/share/thirdreality/wakewords)
--wakeword-models <ids>  Comma-separated model IDs (default: okay_nabu)
--debug                  Enable debug logging
--help                   Show help
```

## Source layout

```
proto/                      Vendored api.proto (aioesphomeapi v42.7.0)
src/main.cpp                CLI, startup, epoll main loop
src/protocol/               ESPHome wire framing + TCP server
src/state/                  Preferences (sound.json) + ServerState
src/entities/               All 12 ESPHome entities
src/audio/                  LibMpvPlayer, AudioCapture, PcmRingBuffer,
                            MicroFeatures, MicroWakeWord, TfliteRuntime,
                            WakeWordEngine, WebRtcProcessor, IAudioPlayer
src/satellite/              Voice pipeline state machine
src/tr/                     ThirdReality integration (LED, GPIO, home
                            button, volume, sendspin, supervisor, OTA,
                            timezone sync, sound.json watcher)
src/tools/                  Dev tools (micro_features_dump, tflite_inspect,
                            wake_word_dump)
src/util/                   Log helper
third_party/microfrontend/  TFLM microfrontend + kissfft sources
third_party/tflite_c/       Prebuilt libtensorflowlite_c.so (trspk, GLIBC≤2.29)
wakewords/microwakeword/    MicroWakeWord .tflite + .json models
wakewords/openwakeword/     OpenWakeWord .tflite + .json (+ mel/embedding)
sounds/                     UI feedback sounds (wake, processing, timer, mute)
test/                       On-target verification scripts
```

## Dependencies (Buildroot)

host-protobuf, protobuf, json-for-modern-cpp, mpv, pulseaudio,
webrtc-audio-processing, libcurl. Plus the vendored
libtensorflowlite_c.so (dlopen'd at runtime, not linked).

## Key notes

- `BR2_STRIP_EXCLUDE_FILES="libtensorflowlite_c.so"` is required in
  defconfig — Buildroot's strip pass damages the prebuilt .so.
- The vendored tflite .so MUST be the trspk-specific build (max
  GLIBC_2.29). The generic linux_arm64 build requires GLIBC_2.34
  which exceeds our toolchain's glibc 2.31.
