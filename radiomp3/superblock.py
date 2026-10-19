"""Superblock layer: Reed-Solomon over 15 rows, Adler-32 per row, row header.

Superblock = 13 data rows + 2 parity rows of 896 bytes each. Each data row
is split into 64 columns of 14 bytes. For column c the 13 data rows give a
182-byte message; its 28 parity bytes sit at offset c*28 of the 1792-byte
parity area (rows 14 and 15). That is RS(210,182), interleaved by column.

Data row:
    0..9    header, every byte XORed with 0xA5
              0..1  id (little-endian)
              2..5  offset (little-endian)
              6..9  total length (little-endian)
    10..13  Adler-32 of the whole row with these 4 bytes set to zero
    stream rows (id % 10 == 0, id not 0 or 100): payload at 16, up to 880 bytes
    file rows   (everything else): 24 bytes file info at 14, payload at 38,
                up to 858 bytes
"""

import struct
import zlib
from dataclasses import dataclass, field

from . import rs
from .teletext import DATA_ROWS, ROW_SIZE, ROWS

COLUMNS = 64
COLUMN_WIDTH = 14
PARITY_OFFSET = DATA_ROWS * ROW_SIZE
SB_SIZE = ROWS * ROW_SIZE
HEADER_XOR = 0xA5
STREAM_PAYLOAD = 880
FILE_PAYLOAD = 858
IGNORED_ID = 100


@dataclass
class Chunk:
    kind: str  # "stream" or "file"
    id: int
    offset: int
    total: int
    data: bytes
    info: bytes = b""
    row: int = 0


@dataclass
class FecStats:
    superblocks: int = 0
    rows_received: int = 0
    rows_bad_before: int = 0
    rows_bad_after: int = 0
    rows_missing: int = 0
    codewords_corrected: int = 0
    symbols_corrected: int = 0
    codewords_failed: int = 0
    chunks: int = 0
    rows_skipped: int = 0


def adler_ok(row):
    stored = struct.unpack_from("<I", row, 10)[0]
    tmp = bytearray(row)
    tmp[10:14] = b"\0\0\0\0"
    return zlib.adler32(bytes(tmp)) == stored


def set_adler(row):
    row[10:14] = b"\0\0\0\0"
    struct.pack_into("<I", row, 10, zlib.adler32(bytes(row)))


def _cw_offsets(c):
    offs = []
    for r in range(DATA_ROWS):
        base = r * ROW_SIZE + c * COLUMN_WIDTH
        offs.extend(range(base, base + COLUMN_WIDTH))
    base = PARITY_OFFSET + c * rs.NPAR
    offs.extend(range(base, base + rs.NPAR))
    return offs


CW_OFFSETS = [_cw_offsets(c) for c in range(COLUMNS)]


class SuperblockDecoder:
    def __init__(self, use_erasures=True):
        self.use_erasures = use_erasures
        self.stats = FecStats()

    def decode(self, sb):
        """Return the list of Chunks from one teletext Superblock."""
        st = self.stats
        st.superblocks += 1
        buf = bytearray(SB_SIZE)
        missing = bytearray(SB_SIZE)  # 1 where the byte never arrived
        for r in range(1, ROWS + 1):
            base = (r - 1) * ROW_SIZE
            page = sb.pages.get(r)
            if page is None:
                missing[base:base + ROW_SIZE] = b"\1" * ROW_SIZE
                if r <= DATA_ROWS:
                    st.rows_missing += 1
                continue
            buf[base:base + ROW_SIZE] = page.data
            for a, b in page.missing_ranges():
                missing[base + a:base + b] = b"\1" * (b - a)
            if r <= DATA_ROWS:
                st.rows_received += 1

        before = bytes(buf)
        ok_before = [adler_ok(before[r * ROW_SIZE:(r + 1) * ROW_SIZE]) for r in range(DATA_ROWS)]
        st.rows_bad_before += ok_before.count(False)

        for offs in CW_OFFSETS:
            cw = bytes(buf[o] for o in offs)
            if rs.check(cw):
                continue
            fixed = self._fix(cw, offs, missing, ok_before)
            if fixed is None:
                st.codewords_failed += 1
                continue
            data, n = fixed
            st.codewords_corrected += 1
            st.symbols_corrected += n
            for o, v in zip(offs, data):
                buf[o] = v

        chunks = []
        for r in range(DATA_ROWS):
            row = bytes(buf[r * ROW_SIZE:(r + 1) * ROW_SIZE])
            if not adler_ok(row):
                old = before[r * ROW_SIZE:(r + 1) * ROW_SIZE]
                if ok_before[r]:
                    row = old
                else:
                    st.rows_bad_after += 1
                    continue
            chunk = parse_row(row, r + 1)
            if chunk is None:
                st.rows_skipped += 1
                continue
            st.chunks += 1
            chunks.append(chunk)
        return chunks

    def _fix(self, cw, offs, missing, ok_before):
        # 1) what the original player did: errors only
        try:
            return rs.decode(cw)
        except rs.ReedSolomonError:
            pass
        if not self.use_erasures:
            return None
        # 2) bytes that never arrived are known erasures
        erased = [i for i, o in enumerate(offs) if missing[o]]
        if 0 < len(erased) <= rs.NPAR:
            try:
                return rs.decode(cw, erase_pos=erased)
            except rs.ReedSolomonError:
                pass
        # 3) additionally treat rows with a bad checksum as erasures
        bad_rows = {r for r in range(DATA_ROWS) if not ok_before[r]}
        extra = [i for i in range(DATA_ROWS * COLUMN_WIDTH) if i // COLUMN_WIDTH in bad_rows]
        erased2 = sorted(set(erased) | set(extra))
        if erased2 != erased and len(erased2) <= rs.NPAR:
            try:
                return rs.decode(cw, erase_pos=erased2)
            except rs.ReedSolomonError:
                pass
        return None


def parse_row(row, row_index=0):
    hdr = bytes(b ^ HEADER_XOR for b in row[:10])
    ident, offset, total = struct.unpack("<HII", hdr)
    remaining = total - offset
    if ident == IGNORED_ID:
        return None
    if ident != 0 and ident % 10 == 0:
        size = STREAM_PAYLOAD if remaining >= STREAM_PAYLOAD else remaining
        if size <= 0:
            return None
        return Chunk("stream", ident, offset, total, bytes(row[16:16 + size]), row=row_index)
    if remaining <= 0:
        return None
    size = min(remaining, FILE_PAYLOAD)
    return Chunk("file", ident, offset, total, bytes(row[38:38 + size]), bytes(row[14:38]), row_index)


def build_row(kind, ident, offset, total, data, info=b""):
    """Inverse of parse_row, used by the test transmitter."""
    row = bytearray(ROW_SIZE)
    struct.pack_into("<HII", row, 0, ident, offset, total)
    if kind == "stream":
        row[16:16 + len(data)] = data
    else:
        row[14:14 + len(info)] = info[:24]
        row[38:38 + len(data)] = data
    for i in range(10):
        row[i] ^= HEADER_XOR
    set_adler(row)  # the checksum covers the obfuscated header, as on air
    return row


def build_parity(data_rows):
    """Return the 1792-byte parity area for 13 data rows (bytes-like)."""
    blob = b"".join(data_rows)
    out = bytearray(COLUMNS * rs.NPAR)
    for c in range(COLUMNS):
        msg = bytes(blob[o] for o in CW_OFFSETS[c][:DATA_ROWS * COLUMN_WIDTH])
        out[c * rs.NPAR:(c + 1) * rs.NPAR] = rs.encode(msg)
    return bytes(out)
