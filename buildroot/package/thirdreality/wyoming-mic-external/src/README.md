# Wyoming External Microphone

[Wyoming protocol](https://github.com/rhasspy/wyoming) server that runs an external program to get microphone input.

The external program must stream raw PCM audio to its standard output, and its format must match the `--rate`, `--width`, and `--channel` arguments provided to the server.
It's recommended that you only stream 16Khz 16-bit mono.

## Installation

``` sh
script/setup
```


## Example

Run a server that streams audio from `arecord`:

``` sh
script/run \
  --program 'arecord -r 16000 -c 1 -f S16_LE -t raw' \
  --rate 16000 \
  --width 2 \
  --channels 1 \
  --uri 'tcp://127.0.0.1:10600'
```
