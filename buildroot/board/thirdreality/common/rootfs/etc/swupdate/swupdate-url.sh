#!/bin/sh
#
# Copyright (c) 2022 Amlogic, Inc. All rights reserved.
# This source code is subject to the terms and conditions
# defined in the file 'LICENSE' which is part of this source code package.
# Description: swupdate url file
#
SWUPDATE_PATH=/data/swupdate

OTA_URL=$1
OTA_SERVER=$(echo $OTA_URL | sed 's/^.*:\/\/\(.*\):.*$/\1/')

echo "OTA Server: $OTA_SERVER, URL:$OTA_URL"
ping -c 1 $OTA_SERVER
if [ $? != 0 ]; then
    echo "Your network can't connect to $OTA_SERVER!!!"
    echo "Something is wrong!!!"
    exit 1
fi
/etc/swupdate/backup_info.sh
touch $SWUPDATE_PATH/enable-network-ota
echo "export SWUPDATE_OTA_SERVER=$OTA_SERVER" >> $SWUPDATE_PATH/apply_info.sh

urlmisc write "$OTA_URL"

