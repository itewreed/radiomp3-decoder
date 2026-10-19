import hashlib
import json
import os
import random

import pytest

from radiomp3 import hamming, rs
from radiomp3.encoder import damage, file_rows, interleave, packets, stream_rows
from radiomp3.sink import Sink
from radiomp3.superblock import SuperblockDecoder
from radiomp3.teletext import PageAssembler, read_t42

DATA = os.path.join(os.path.dirname(__file__), "data")


def decode_packets(pkts, use_erasures=True):
    pa = PageAssembler()
    dec = SuperblockDecoder(use_erasures=use_erasures)
    chunks = []
    for pk in pkts:
        for sb in pa.feed(pk):
            chunks += dec.decode(sb)
    for sb in pa.flush():
        chunks += dec.decode(sb)
    return chunks, pa, dec


def payload(seed, n):
    rnd = random.Random(seed)
    return bytes(rnd.randrange(256) for _ in range(n))


def test_hamming_roundtrip_and_single_bit_correction():
    for v in range(16):
        code = hamming.encode(v)
        assert hamming.decode(code, correct=False) == v
        for bit in range(8):
            assert hamming.decode(code ^ (1 << bit), correct=True) == v
            assert hamming.decode(code ^ (1 << bit), correct=False) is None


def test_rs_parity_matches_original_player():
    # 13 data rows + parity area produced by CFec::encodeBlocks of the player
    blob = open(os.path.join(DATA, "rs_vector_player.bin"), "rb").read()
    data, parity = blob[:13 * 896], blob[13 * 896:]
    for c in range(64):
        msg = b"".join(data[r * 896 + c * 14:r * 896 + c * 14 + 14] for r in range(13))
        assert rs.encode(msg) == parity[c * 28:(c + 1) * 28]


@pytest.mark.parametrize("errors,erasures", [(14, 0), (0, 28), (6, 16), (10, 8)])
def test_rs_correction_capacity(errors, erasures):
    rnd = random.Random(errors * 100 + erasures)
    msg = bytes(rnd.randrange(256) for _ in range(182))
    cw = msg + rs.encode(msg)
    bad = bytearray(cw)
    pos = rnd.sample(range(210), errors + erasures)
    for p in pos:
        bad[p] ^= rnd.randrange(1, 256)
    fixed, _ = rs.decode(bytes(bad), erase_pos=pos[errors:])
    assert fixed == cw


def test_rs_too_many_errors_is_detected():
    rnd = random.Random(3)
    msg = bytes(rnd.randrange(256) for _ in range(182))
    bad = bytearray(msg + rs.encode(msg))
    for p in rnd.sample(range(210), 20):
        bad[p] ^= 0x5A
    with pytest.raises(rs.ReedSolomonError):
        rs.decode(bytes(bad))


def test_matches_original_player_output():
    """Superblocks and chunks equal what the original player code produced."""
    ref = json.load(open(os.path.join(DATA, "player_reference.json")))
    pa = PageAssembler()
    sbs = []
    for pk in read_t42(os.path.join(DATA, "reference_signal.t42")):
        sbs += pa.feed(pk)
    sbs += pa.flush()
    sb_bytes = [b"".join(bytes(sb.pages[r].data) for r in range(1, 16)) for sb in sbs]
    assert [hashlib.sha1(b).hexdigest() for b in sb_bytes] == ref["superblocks_sha1"]

    dec = SuperblockDecoder()
    got = []
    for sb in sbs:
        for c in dec.decode(sb):
            got.append({"kind": c.kind, "id": c.id, "offset": c.offset, "total": c.total,
                        "len": len(c.data), "sha1": hashlib.sha1(c.data).hexdigest()})
    assert got == ref["chunks"]


def test_clean_roundtrip(tmp_path):
    stream = payload(1, 50_000)
    cover = payload(2, 12_345)
    pk = list(packets(interleave(stream_rows(10, stream), file_rows(23, cover, "cover.jpg"))))
    chunks, _, dec = decode_packets(pk)
    sink = Sink(str(tmp_path))
    for c in chunks:
        sink.add(c)
    streams, files = sink.close()
    assert (tmp_path / streams[0]["path"]).read_bytes() == stream
    assert files[0]["complete"]
    assert (tmp_path / "files" / "cover.jpg").read_bytes() == cover
    assert dec.stats.codewords_corrected == 0


def test_lost_lines_are_recovered_with_erasures():
    stream = payload(4, 60_000)
    rows = list(stream_rows(10, stream))
    pk = list(damage(packets(rows), drop=0.02, seed=12))
    chunks, _, dec = decode_packets(pk, use_erasures=True)
    data = b"".join(c.data for c in sorted(chunks, key=lambda c: c.offset))
    assert data == stream
    assert dec.stats.rows_bad_after == 0

    # the original player strategy (errors only) loses data on the same signal
    chunks_old, _, dec_old = decode_packets(pk, use_erasures=False)
    assert dec_old.stats.rows_bad_after > 0


def test_bit_errors_are_corrected():
    stream = payload(5, 40_000)
    pk = list(damage(packets(stream_rows(10, stream)), flip=0.003, seed=12))
    chunks, _, dec = decode_packets(pk)
    data = b"".join(c.data for c in sorted(chunks, key=lambda c: c.offset))
    assert data == stream
    assert dec.stats.symbols_corrected > 0


def test_raw_vbi_slicer():
    np = pytest.importorskip("numpy")
    from radiomp3.vbi import render_line, slice_line, TELETEXT_RATE

    spb = 35_468_950.0 / TELETEXT_RATE
    rng = np.random.default_rng(1)
    pkts = list(packets(stream_rows(10, payload(6, 3000))))[:50]
    for i, pk in enumerate(pkts):
        line = render_line(pk, start=100 + (i % 7) * 3.3, noise=6, rng=rng)
        assert slice_line(line, spb, search=220) == pk
