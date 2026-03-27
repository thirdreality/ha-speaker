#!/bin/sh

# find "$TARGET_DIR/usr/lib/python3.11/site-packages/numpy" \
#     -type d \( -name tests -o -name '__pycache__' \) \
#     -prune -exec rm -rf {} +

rm -rf $TARGET_DIR/usr/lib/python3.11/site-packages/pymicro_wakeword/models

exit 0
