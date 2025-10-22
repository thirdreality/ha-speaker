# Wyoming External Sound

[Wyoming protocol](https://github.com/rhasspy/wyoming) server that runs an external program to play audio.

The external program must receive raw PCM audio on its standard input.
The format will match the `--rate`, `--width`, and `--channel` arguments provided to the server.

## Installation

``` sh
script/setup
```


## Example

Run a server that plays audio with `aplay`:

``` sh
script/run \
  --uri 'tcp://127.0.0.1:10601' \
  --program 'aplay -r 22050 -c 1 -f S16_LE -t raw' \
  --rate 22050 \
  --width 2 \
  --channels 1
```
