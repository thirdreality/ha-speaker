# Python openWakeWord

Alternative Python library for [openWakeWord](https://github.com/dscripka/openWakeWord).

Uses a [pre-compiled Tensorflow Lite library](https://github.com/tphakala/tflite_c).


## Install

``` sh
pip3 install pyopen-wakeword
```


## Usage

``` python
from pyopen_wakeword import OpenWakeWord, OpenWakeWordFeatures, Model

oww = OpenWakeWord.from_builtin(Model.OKAY_NABU)
oww_features = OpenWakeWordFeatures()

# Audio must be 16-bit mono at 16Khz
while audio := get_10ms_of_audio():
    assert len(audio) == 160 * 2  # 160 samples
    for features in oww_features.process_streaming(audio):
        for prob in oww.process_streaming(features):
            if prob > 0.5:
                print("Detected!")
```


## Command-Line

### WAVE files

``` sh
python3 -m pyopen_wakeword --model 'okay_nabu' /path/to/*.wav
```

### Live

``` sh
arecord -r 16000 -c 1 -f S16_LE -t raw | \
  python3 -m pyopen_wakeword --model 'okay_nabu'
```
