#!/bin/sh

BT_PIDFILE="/var/run/thirdreality/bluetooth.pid"
LED_PIDFILE="/var/run/thirdreality/btgatt_led.pid"
GATT_PIDFILE="/var/run/thirdreality/btgatt_server.pid"

mkdir -p /var/run/thirdreality/

check_hci0()
{
	local cnt=10
	while [ $cnt -gt 0 ]; do
		hciconfig hci0 2> /dev/null
		if [ $? -eq 1 ];then
			# echo "checking hci0 ......."
			sleep 1
			cnt=$((cnt - 1))
		else
			break
		fi
	done

	if [ $cnt -eq 0 ];then
		echo "hci0 bring up failed!!!"
		exit 0
	fi
}

led_loop() {
    while pidof btgatt-server > /dev/null; do
        dbus-send --system --type=signal /com/3r/EventBus \
            com._3reality.EventBus.LedShow boolean:false \
            array:string:'/usr/share/thirdreality/animation/ntf_incoming.animation'

        sleep 3
    done
}

service_down()
{
	start-stop-daemon -K -q -p "$GATT_PIDFILE" 2>/dev/null
    rm -f "$GATT_PIDFILE"

    start-stop-daemon -K -q -p "$LED_PIDFILE" 2>/dev/null
    rm -f "$LED_PIDFILE"

    hciconfig hci0 down 2>/dev/null
}

service_up()
{
	check_hci0
	hciconfig hci0 up
	hciconfig hci0 piscan
	hciconfig hci0 leadv 3
	hcitool -i hci0 cmd 0x08 0x000A 01
	sleep 1

    start-stop-daemon -S -q \
        -p "$GATT_PIDFILE" -m -b \
        -x /usr/bin/btgatt-server

    if [ -f "$LED_PIDFILE" ]; then
        local led_pid=$(cat "$LED_PIDFILE" 2>/dev/null)
        if [ -n "$led_pid" ] && kill -0 "$led_pid" 2>/dev/null; then
            return 0
        else
            rm -f "$LED_PIDFILE"
        fi
	else
		led_loop &
		echo $! > "$LED_PIDFILE"
    fi
}

Blue_start()
{
	echo 0 > /sys/class/rfkill/rfkill0/state
	usleep 500000
	echo 1 > /sys/class/rfkill/rfkill0/state

    start-stop-daemon -S -q \
        -p "$BT_PIDFILE" -m -b \
        -x /usr/bin/brcm_patchram_plus -- \
        --enable_hci --no2bytes --tosleep 200000 --baudrate 115200 \
        -patchram /etc/bluetooth/bcm4343a1.hcd /dev/ttyS1
}

Blue_stop()
{
	echo -n "Stopping bluez"
	service_down
    start-stop-daemon -K -q -p "$BT_PIDFILE" 2>/dev/null
    rm -f "$BT_PIDFILE"
	sleep 2
	echo 0 > /sys/class/rfkill/rfkill0/state
}

case "$1" in
	start)
		Blue_start &
		;;
	stop)
		Blue_stop
		;;
	up)
		service_up
		;;
	down)
		service_down &
		;;
	restart)
		service_down
		Blue_stop
		sleep 1
		Blue_start
		service_up
		aplay -Dsoftvol -c2 /usr/share/thirdreality/audio/change_wifi.wav &
		;;
	*)
		echo "Usage: $0 {start|stop|up|down|restart}"
		exit 1
esac

exit $?

