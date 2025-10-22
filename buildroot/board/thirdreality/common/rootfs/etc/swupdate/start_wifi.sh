#!/bin/sh
#
# Copyright (c) 2022 Amlogic, Inc. All rights reserved.
# This source code is subject to the terms and conditions
# defined in the file 'LICENSE' which is part of this source code package.
# Description: start wifi file
#
multi_wifi_load_driver station 1
sleep 3
wpa_supplicant -iwlan0 -Dnl80211 -c /etc/wpa_supplicant.conf &
sleep 3
dhcpcd
sleep 3
