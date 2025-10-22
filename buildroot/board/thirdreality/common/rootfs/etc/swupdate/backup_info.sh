#!/bin/sh
#
# Copyright (c) 2022 Amlogic, Inc. All rights reserved.
# This source code is subject to the terms and conditions
# defined in the file 'LICENSE' which is part of this source code package.
# Description: backup info file
#
SWUPDATE_PATH=/data/swupdate

rm -fr $SWUPDATE_PATH
mkdir -p $SWUPDATE_PATH

#Copy swupdate script
cp -a /etc/swupdate/* $SWUPDATE_PATH/

#Copy Wifi setting and drivers
mkdir -p $SWUPDATE_PATH/etc
cp -a /etc/wifi $SWUPDATE_PATH/etc/
cp -a /etc/wpa_supplicant.conf $SWUPDATE_PATH/etc/
cp -a /etc/dhcpcd.conf $SWUPDATE_PATH/etc/

wifi_module=$(lsmod | grep "\<\(dhd\|8723ds\)\>" | cut -d ' ' -f1)
if [ $wifi_module ]
then
  for ko in $(find /lib/modules/ -name $wifi_module.ko)
  do
    ko_path=$(dirname $ko)
    mkdir -p $SWUPDATE_PATH/$ko_path/
    cp $ko $SWUPDATE_PATH/$ko_path/
  done
fi
