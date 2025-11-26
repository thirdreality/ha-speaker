# pyRing Buffer

A pure Python ring/circular buffer for bytes.

``` sh
pip install pyring-buffer
```

``` python
from pyring_buffer import RingBuffer

rb = RingBuffer(10)  # max 10 bytes

# Put only 5 bytes in
rb.put(bytes([1, 2, 3, 4, 5]))

# Everything is there
assert rb.getvalue() == bytes([1, 2, 3, 4, 5])

# Put a total of 12 bytes in
rb.put(bytes([6, 7, 8, 9, 10, 11, 12]))

# First 2 bytes are gone
assert rb.getvalue() == bytes([3, 4, 5, 6, 7, 8, 9, 10, 11, 12])
```

