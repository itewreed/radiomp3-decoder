"""Hamming 8/4 as used for teletext addressing (ETS 300 706, section 8.2)."""

ENCODE = bytes([
    0x15, 0x02, 0x49, 0x5E, 0x64, 0x73, 0x38, 0x2F,
    0xD0, 0xC7, 0x8C, 0x9B, 0xA1, 0xB6, 0xFD, 0xEA,
])

ERROR = 0xFF


def _build_tables():
    strict = bytearray([ERROR] * 256)
    correcting = bytearray([ERROR] * 256)
    for value, code in enumerate(ENCODE):
        strict[code] = value
    for byte in range(256):
        best = None
        for value, code in enumerate(ENCODE):
            dist = bin(byte ^ code).count("1")
            if dist <= 1:
                best = value
        if best is not None:
            correcting[byte] = best
    return bytes(strict), bytes(correcting)


# STRICT matches the table inside the original player (only the 16 exact
# codewords are accepted). CORRECTING additionally fixes single-bit errors.
STRICT, CORRECTING = _build_tables()


def encode(nibble):
    return ENCODE[nibble & 0x0F]


def decode(byte, correct=True):
    """Return the 4-bit value or None if the byte is not decodable."""
    value = (CORRECTING if correct else STRICT)[byte]
    return None if value == ERROR else value


def decode_mrag(b0, b1, correct=True):
    """Return (magazine, packet) from the two address bytes, or None.

    Magazine is returned the way it is coded on air: 0 means magazine 8.
    """
    lo = decode(b0, correct)
    hi = decode(b1, correct)
    if lo is None or hi is None:
        return None
    value = (hi << 4) | lo
    return value & 0x07, value >> 3


def encode_mrag(magazine, packet):
    value = (magazine & 0x07) | (packet << 3)
    return bytes([encode(value & 0x0F), encode(value >> 4)])
