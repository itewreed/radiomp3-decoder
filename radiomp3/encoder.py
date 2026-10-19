"""Test transmitter: builds a .t42 packet stream the way the broadcast did.

Useful to test the decoder without a real recording, and to document the
format in executable form.
"""

import random

from . import hamming
from .superblock import (FILE_PAYLOAD, IGNORED_ID, STREAM_PAYLOAD, build_parity,
                         build_row)
from .teletext import DATA_ROWS, LAST_PACKET, MAGAZINE, P1_PAYLOAD, PN_PAYLOAD, ROW_SIZE


def stream_rows(ident, data):
    total = len(data)
    for off in range(0, total, STREAM_PAYLOAD):
        yield build_row("stream", ident, off, total, data[off:off + STREAM_PAYLOAD])


def file_rows(ident, data, name=""):
    info = name.encode("latin-1", "replace")[:24]
    for off in range(0, len(data), FILE_PAYLOAD):
        yield build_row("file", ident, off, len(data), data[off:off + FILE_PAYLOAD], info)


def interleave(*sources):
    """Round-robin over several row generators."""
    iters = [iter(s) for s in sources]
    while iters:
        for it in list(iters):
            try:
                yield next(it)
            except StopIteration:
                iters.remove(it)


def superblocks(rows):
    """Group rows into lists of 15 rows (13 data + 2 parity)."""
    filler = build_row("stream", IGNORED_ID, 0, 0, b"")
    batch = []
    for row in rows:
        batch.append(bytes(row))
        if len(batch) == DATA_ROWS:
            yield _with_parity(batch)
            batch = []
    if batch:
        batch += [bytes(filler)] * (DATA_ROWS - len(batch))
        yield _with_parity(batch)


def _with_parity(batch):
    parity = build_parity(batch)
    return batch + [parity[:ROW_SIZE], parity[ROW_SIZE:]]


def page_packets(row_index, data, aux, page_number=0x00):
    """Return the 24 teletext packets that carry one 896-byte row."""
    mrag = lambda n: hamming.encode_mrag(MAGAZINE, n)
    header = bytearray(mrag(0))
    for nibble in (page_number & 0xF, page_number >> 4, 0, 0, 0, 0, 0, 0):
        header.append(hamming.encode(nibble))
    header += b" " * (42 - len(header))
    packets = [bytes(header)]
    p1 = bytearray(mrag(1))
    p1 += bytes([hamming.encode(row_index), hamming.encode(aux)])
    p1 += data[:P1_PAYLOAD]
    packets.append(bytes(p1))
    pos = P1_PAYLOAD
    for n in range(2, LAST_PACKET + 1):
        pk = bytearray(mrag(n))
        pk.append(hamming.encode(row_index))
        pk += data[pos:pos + PN_PAYLOAD]
        pos += PN_PAYLOAD
        packets.append(bytes(pk))
    return packets


def packets(rows):
    """Turn data rows into the complete teletext packet sequence."""
    for count, sb in enumerate(superblocks(rows)):
        aux = count % 15 + 1
        for r, data in enumerate(sb, start=1):
            yield from page_packets(r, data, aux)


def damage(packet_iter, drop=0.0, flip=0.0, seed=0):
    """Simulate a bad reception: drop whole packets, flip random bytes."""
    rnd = random.Random(seed)
    for pk in packet_iter:
        if rnd.random() < drop:
            continue
        if flip:
            pk = bytearray(pk)
            for i in range(len(pk)):
                if rnd.random() < flip:
                    pk[i] ^= 1 << rnd.randrange(8)
            pk = bytes(pk)
        yield pk
