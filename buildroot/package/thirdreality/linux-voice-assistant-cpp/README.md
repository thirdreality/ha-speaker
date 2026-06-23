# linux-voice-assistant-cpp

C++ rewrite of [OHF-Voice/linux-voice-assistant](https://github.com/OHF-Voice/linux-voice-assistant.git),
a Python-based voice satellite for Home Assistant. This project is a
full native replacement targeting embedded Linux (Amlogic A113X,
aarch64, Buildroot).

## Features

- ESPHome native API server (TCP 6053, plain-text framing, protobuf)
- mDNS auto-discovery via avahi (_esphomelib._tcp)
- 11 entities: mute switch, thinking-sound switch, 3× wake-word
  sensitivity numbers, mic gain, mic volume, mic noise select,
  media player, home button event, firmware update
- Voice satellite state machine (wake → STT stream → TTS playback →
  timer ring loop)
- MicroWakeWord inference (TFLM microfrontend + TFLite C runtime,
  dlopen)
- OpenWakeWord inference (melspectrogram + embedding TFLite models)
- WebRTC AGC + noise suppression + AEC (hardware-loopback echo
  cancellation when using ALSA capture backend with reference channels)
- ALSA capture backend with multi-channel support (mic + reference
  channels for AEC)
- PulseAudio capture backend (legacy fallback)
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
--name <name>              Device name (from device.json)
--port <port>              TCP port (default: 6053)
--host <addr>              Bind address (default: 0.0.0.0)
--preferences-file <p>     Prefs file (default: /data/conf/sound.json)
--audio-device <dev>       PulseAudio device (default: system default)
--wakeword-type <type>     "micro" or "open" (default: micro)
--wakeword-models <ids>    Comma-separated model IDs (default: okay_nabu)
--capture-backend <b>      Capture backend: alsa|pulse (default: alsa)
--capture-alsa-device <d>  ALSA capture device (default: hw:0,4)
--capture-mic-channel <n>  0-based mic channel in ALSA stream (default: 0)
--capture-ref-channels <c> Comma-separated 0-based ref channels for AEC;
                           empty or "none" disables AEC (default: 2,3)
--continue-conversation-delay <s>
                           Seconds to wait after TTS finishes before opening
                           the mic for a continued conversation (default: 0.5)
--debug                    Enable debug logging
--help                     Show help
```

The wake-word model directory is derived from `--wakeword-type`:
`/usr/share/thirdreality/wakewords/microwakeword/` or `.../openwakeword/`.

## Source layout

```
proto/                      Vendored api.proto + api_options.proto
                            (aioesphomeapi v42.7.0)
src/main.cpp                CLI, startup, epoll main loop
src/protocol/               ESPHome wire framing, TCP server, mDNS
src/state/                  Preferences (sound.json) + ServerState
src/entities/               ESPHome entities
src/audio/                  AudioCapture, LibMpvPlayer, PcmRingBuffer,
                            MicroFeatures, MicroWakeWord, OpenWakeWord,
                            OpenWakeWordFeatures, WakeWordScanner,
                            WakeWordEngine, TfliteRuntime,
                            WebRtcProcessor, IAudioPlayer
src/satellite/              Voice pipeline state machine
src/tr/                     ThirdReality integration (LED, GPIO, home
                            button, volume, sendspin, supervisor, OTA,
                            timezone sync, sound.json watcher)
src/tools/                  Dev tools (micro_features_dump, tflite_inspect,
                            wake_word_dump, aec_loopback_test)
src/util/                   Log helper
third_party/microfrontend/  TFLM microfrontend + kissfft sources
third_party/tflite_c/       Prebuilt libtensorflowlite_c.so (GLIBC≤2.29)
wakewords/microwakeword/    MicroWakeWord .tflite + .json models
wakewords/openwakeword/     OpenWakeWord .tflite + .json (+ mel/embedding)
sounds/                     UI feedback sounds (wake_word_triggered,
                            processing, timer_finished, mute_switch_on,
                            mute_switch_off)
```

## Dependencies (Buildroot)

host-protobuf, protobuf, json-for-modern-cpp, mpv, pulseaudio,
alsa-lib, webrtc-audio-processing, libcurl, avahi. Plus the vendored
libtensorflowlite_c.so (dlopen'd at runtime, not linked).
