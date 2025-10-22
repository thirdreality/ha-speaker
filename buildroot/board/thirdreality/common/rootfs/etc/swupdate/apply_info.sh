#!/bin/sh
#
# Copyright (c) 2022 Amlogic, Inc. All rights reserved.
# This source code is subject to the terms and conditions
# defined in the file 'LICENSE' which is part of this source code package.
# Description: apply info file
#
SWUPDATE_PATH=$1/swupdate

#Remount recovery as read write
mount -o remount,rw /
mkdir -p /var/db

cp $SWUPDATE_PATH/etc/* /etc  -a
cp $SWUPDATE_PATH/lib/* /lib  -a

