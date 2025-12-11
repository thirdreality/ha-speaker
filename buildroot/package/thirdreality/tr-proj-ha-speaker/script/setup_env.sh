#!/bin/sh

echo "Setting up ThirdReality environment..."
dmesg -n 4

mkdir -p /data/conf
SOUND_CONF="/data/conf/sound.json"
SETTINGS_CONF="/data/conf/settings.json"
DEVICE_CONF_BAK="/usr/share/thirdreality/conf/device.json"
DEVICE_CONF="/data/conf/device.json"

# mic_mute=1->unmute
if [ ! -s "$SOUND_CONF" ] || ! jq empty "$SOUND_CONF" 2>/dev/null; then
    cat > "$SOUND_CONF" <<EOF
{
    "volume": 30,
    "mic_gain": 30,
    "mic_mute": 1
}
EOF
fi

VOL=$(jq -r '.volume // 30' "$SOUND_CONF")
MIC_GAIN=$(jq -r '.mic_gain // 30' "$SOUND_CONF")
MIC_MUTE=$(jq -r '.mic_mute // 1' "$SOUND_CONF")

if [ ! -f "$DEVICE_CONF" ] || [ ! -s "$DEVICE_CONF" ] || ! jq empty "$DEVICE_CONF" 2>/dev/null; then
    cp "$DEVICE_CONF_BAK" "$DEVICE_CONF"
fi

MAC_ADDRESS=$(ifconfig wlan0 | grep "HWaddr" | awk '{print $5}')
while [ -z "$MAC_ADDRESS" ]; do
    sleep 0.5
    MAC_ADDRESS=$(ifconfig wlan0 | grep "HWaddr" | awk '{print $5}')
done
DEVICE_NAME="3RSPK-${MAC_ADDRESS//:/}"

CURRENT_MAC=$(jq -r '.device.macAddress // ""' "$DEVICE_CONF")
CURRENT_NAME=$(jq -r '.device.name // ""' "$DEVICE_CONF")

if [ "$CURRENT_MAC" != "$MAC_ADDRESS" ] || [ "$CURRENT_NAME" != "$DEVICE_NAME" ]; then
    jq --arg mac "$MAC_ADDRESS" --arg name "$DEVICE_NAME" \
        '.device.macAddress = $mac | .device.name = $name' \
        "$DEVICE_CONF" > "${DEVICE_CONF}.tmp" && mv "${DEVICE_CONF}.tmp" "$DEVICE_CONF"
    if ! cmp -s "$DEVICE_CONF" "$DEVICE_CONF_BAK"; then
        cp "$DEVICE_CONF" "$DEVICE_CONF_BAK"
    fi
fi

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

killall tr_ledring 2>/dev/null || true
sleep 0.2
/usr/share/thirdreality/bin/tr_ledring &
sleep 0.5
dbus-send --system --type=signal /com/3r/EventBus com._3reality.EventBus.LedShow boolean:false array:string:'/usr/share/thirdreality/animation/none.animation'

sync
