#!/bin/sh

source /usr/share/thirdreality/script/setup_env.sh

case "$1" in
    start)
        netmonitor start &
        # tr_ledring &
        # dbus-send --system --type=signal /com/3r/EventBus com._3reality.EventBus.LedShow boolean:false array:string:'/usr/share/thirdreality/animation/none.animation'
        ;;
    stop)
        netmonitor stop
        ;;
    *)
        echo "Usage: $0 {start|stop}"
        exit 1
        ;;
esac
