#!/bin/sh

# set -x
SOUND_CONF="/data/conf/sound.json"
LOCK_FILE="/tmp/sound_config.lock"
VOL_PENDING_FILE="/tmp/volume_pending"
VOL_PID_FILE="/tmp/volume_pid"
VOL_COUNT_FILE="/tmp/volume_count"

vol() {
    action="$1"

    if [ -f "$VOL_COUNT_FILE" ]; then
        count=$(cat "$VOL_COUNT_FILE")
    else
        count=0
    fi
    count=$((count + 1))
    echo "$count" > "$VOL_COUNT_FILE"

    echo "$action" > "$VOL_PENDING_FILE"

    if [ -f "$VOL_PID_FILE" ]; then
        old_pid=$(cat "$VOL_PID_FILE")
        kill $old_pid 2>/dev/null
    fi

    (
        sleep 0.3
        if [ -f "$VOL_PENDING_FILE" ]; then
            pending_action=$(cat "$VOL_PENDING_FILE")
            pending_count=$(cat "$VOL_COUNT_FILE" 2>/dev/null || echo "1")
            rm -f "$VOL_PENDING_FILE"
            rm -f "$VOL_COUNT_FILE"
            do_volume_change "$pending_action" "$pending_count"
        fi
        rm -f "$VOL_PID_FILE"
    ) &

    echo $! > "$VOL_PID_FILE"
}

do_volume_change() {
    action="$1"
    count="${2:-1}"
    
    exec 200>"$LOCK_FILE"
    flock -x 200

    vol=$(jq '.volume' "$SOUND_CONF")

    step=$((10 * count))

    if [ "$action" = "up" ]; then
        vol=$((vol + step))
    elif [ "$action" = "down" ]; then
        vol=$((vol - step))
    fi

    if [ "$vol" -ge 100 ]; then
        vol=100
    elif [ "$vol" -le 0 ]; then
        vol=0
    fi

    pactl set-sink-volume @DEFAULT_SINK@ "$vol"% > /dev/null 2>&1

    echo "Volume $action (x${count}): $vol%"

    tmpfile=$(mktemp)
    jq --argjson v "$vol" '.volume = $v' "$SOUND_CONF" > "$tmpfile" && mv "$tmpfile" "$SOUND_CONF"
    sync

    flock -u 200
    exec 200>&-

    dbus-send --system --type=signal /com/3r/EventBus com._3reality.EventBus.LedShow boolean:false array:string:'/usr/share/thirdreality/animation/volume-changed.animation'
}

factory_reset() {
    if [ -f "/tmp/factory_reset" ];then
        rm -rf /tmp/factory_reset
        exit 0
    else
        touch /tmp/factory_reset
    fi
    paplay /usr/share/thirdreality/audio/factory_reset.wav &
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

set_volume() {
    vol="$1"
    [ -z "$vol" ] && exit 1
    
    if [ "$vol" -ge 100 ]; then
        vol=100
    elif [ "$vol" -le 0 ]; then
        vol=0
    fi
    
    exec 200>"$LOCK_FILE"
    flock -x 200
    
    pactl set-sink-volume @DEFAULT_SINK@ "$vol"% > /dev/null 2>&1
    
    tmpfile=$(mktemp)
    jq --argjson v "$vol" '.volume = $v' "$SOUND_CONF" > "$tmpfile" && mv "$tmpfile" "$SOUND_CONF"
    sync
    
    flock -u 200
    exec 200>&-
    
    echo "SetVolume: $vol%"
    dbus-send --system --type=signal /com/3r/EventBus com._3reality.EventBus.LedShow boolean:false array:string:'/usr/share/thirdreality/animation/volume-changed.animation'
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
    "SetVolume") set_volume "$2" ;;
    "Home") echo "home was pressed";;
    "longpressTap") change_wifi ;;
    "Mute") mic_mute ;;
    "longpressHome") factory_reset ;;
    *) echo "no function to add this case: $1" ;;
esac

exit
