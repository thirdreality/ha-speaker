#!/bin/sh

# set -x
SOUND_CONF="/data/conf/sound.json"

vol() {
    action="$1"

    vol=$(jq '.volume' "$SOUND_CONF")

    if [ "$action" = "up" ]; then
        vol=$((vol+10))
    elif [ "$action" = "down" ]; then
        vol=$((vol-10))
    fi

    if [ "$vol" -ge 100 ]; then
        vol=100
    elif [ "$vol" -le 0 ]; then
        vol=0
    fi

    amixer cset numid=34 "$vol"% > /dev/null 2>&1

    echo "Volume $action: $vol%"

    tmpfile=$(mktemp)
    jq --argjson v "$vol" '.volume = $v' "$SOUND_CONF" > "$tmpfile" && mv "$tmpfile" "$SOUND_CONF"
    sync

    dbus-send --system --type=signal /com/3r/EventBus com._3reality.EventBus.LedShow boolean:false array:string:'/usr/share/thirdreality/animation/volume-changed.animation'
}

factory_reset() {
    if [ -f "/tmp/factory_reset" ];then
        rm -rf /tmp/factory_reset
        exit 0
    else
        touch /tmp/factory_reset
    fi
    echo "factory resetting..."
    dbus-send --system --type=signal /com/3r/EventBus com._3reality.EventBus.LedShow boolean:false array:string:'/usr/share/thirdreality/animation/ntf_incoming.animation'

    sleep 3

    for i in $(seq 3); do
        killall5 -9
        sleep 1
    done

    rm -rf /data/*
    umount /data
    sync
    reboot
}

mic_mute() {
    status=$(cat /sys/class/gpio/gpio438/value)

    if [ $status = "1" ]; then
        status=0
        echo 0 > /sys/class/gpio/gpio438/value
    else
        status=1
        echo 1 > /sys/class/gpio/gpio438/value
    fi

    tmpfile=$(mktemp)
    jq --argjson v "$status" '.mic_mute = $v' "$SOUND_CONF" > "$tmpfile" && mv "$tmpfile" "$SOUND_CONF"
    sync
}

change_wifi() {
    if [ -f "/tmp/change_wifi" ];then
        rm -rf /tmp/change_wifi
        exit 0
    else
        touch /tmp/change_wifi
    fi

    dbus-send --system --type=signal /com/3r/EventBus com._3reality.EventBus.LedShow boolean:false array:string:'/usr/share/thirdreality/animation/ntf_incoming.animation'
    /etc/init.d/S44bluetooth restart
}

case $1 in
    "Volup") vol "up" ;;
    "Voldown") vol "down" ;;
    "Home") echo "home was pressed";;
    "Tap") echo "tap was pressed";;
    "longpressTap") change_wifi ;;
    "Mute") mic_mute ;;
    "longpressHome") factory_reset ;;
    *) echo "no function to add this case: $1" ;;
esac

exit
