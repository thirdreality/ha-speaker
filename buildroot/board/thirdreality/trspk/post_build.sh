#!/bin/sh

rm -rf $TARGET_DIR/usr/lib/python3.11/site-packages/pymicro_wakeword/models

# Store build timestamp so the device boots with a sane default time
# instead of 1970-01-01 (no RTC battery). This accelerates NTP sync
# and avoids TLS/DNS failures caused by expired certificates.
date -u +%Y%m%d%H%M > $TARGET_DIR/etc/build_timestamp

exit 0
