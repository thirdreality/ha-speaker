#!/bin/sh

LED_PIDFILE="/var/run/thirdreality/btgatt_led.pid"

mkdir -p /var/run/thirdreality/

brcm_bt_init()
{
	brcm_patchram_plus --enable_hci --no2bytes --tosleep 200000 --baudrate 115200 -patchram /etc/bluetooth/bcm4343a1.hcd /dev/ttyS1 &
}

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
	killall btgatt-server
	hciconfig hci0 down

	if [ -f "$LED_PIDFILE" ]; then
		kill "$(cat $LED_PIDFILE)" 2>/dev/null
		rm -f "$LED_PIDFILE"
	fi
}

service_up()
{
	killall btgatt-server

	check_hci0
	hciconfig hci0 up
	hciconfig hci0 piscan
	hciconfig hci0 leadv 3
	hcitool -i hci0 cmd 0x08 0x000A 01
	sleep 1
	btgatt-server &

	led_loop &
	echo $! > "$LED_PID_FILE"
}

Blue_start()
{
	echo 0 > /sys/class/rfkill/rfkill0/state
	usleep 500000
	echo 1 > /sys/class/rfkill/rfkill0/state

	brcm_bt_init
}

Blue_stop()
{
	echo -n "Stopping bluez"
	service_down
	killall brcm_patchram_plus
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
	*)
		echo "Usage: $0 {start|stop|up|down}"
		exit 1
esac

exit $?

