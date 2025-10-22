#!/bin/sh

echo "Setting up ThirdReality environment..."

mkdir -p /data/conf
SOUND_CONF="/data/conf/sound.json"
DEVICE_CONF="/data/conf/device.json"

dmesg -n 4

# mic_mute=1->unmute
if [ ! -s "$SOUND_CONF" ] || ! jq empty "$SOUND_CONF" 2>/dev/null; then
    cat > "$SOUND_CONF" <<EOF
{
    "volume": 20,
    "mic_gain": 30,
    "mic_mute": 1
}
EOF
fi

VOL=$(jq -r '.volume // 20' "$SOUND_CONF")
MIC_GAIN=$(jq -r '.mic_gain // 30' "$SOUND_CONF")
MIC_MUTE=$(jq -r '.mic_mute // 1' "$SOUND_CONF")

head -c 38400 /dev/zero | aplay -D softvol -t raw -f S32_LE -c2 -r48000 > /dev/null 2>&1
# set mic gain
amixer cset numid=7 "$MIC_GAIN"% > /dev/null 2>&1
# set volume
amixer cset numid=34 "$VOL"% > /dev/null 2>&1
# enable speaker
if [ ! -d "/sys/class/gpio/gpio414" ]; then
    echo 414 > /sys/class/gpio/export
    echo out > /sys/class/gpio/gpio414/direction
    echo 1 > /sys/class/gpio/gpio414/value
fi

# mic_offline(GPIOA_1) to high to unmute the microphone
if [ ! -d "/sys/class/gpio/gpio438" ]; then
    echo 438 > /sys/class/gpio/export
    echo out > /sys/class/gpio/gpio438/direction
    echo "$MIC_MUTE" > /sys/class/gpio/gpio438/value
fi

tr_ledring &
sleep 0.5
dbus-send --system --type=signal /com/3r/EventBus com._3reality.EventBus.LedShow boolean:false array:string:'/usr/share/thirdreality/animation/none.animation'
