"""Reassembles streams and files from decoded chunks and writes them to disk."""

import hashlib
import json
import os
import re


def guess_extension(data):
    head = data[:16]
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return ".mp3"
    if head.startswith(b"\xff\xd8"):
        return ".jpg"
    if head.startswith(b"GIF8"):
        return ".gif"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"BM"):
        return ".bmp"
    if head.lstrip().startswith(b"[") and b"]" in head:
        return ".ini"
    if head.lstrip()[:1] == b"<":
        return ".html"
    return ".bin"


def info_name(info):
    """Try to read a printable name from the 24-byte file info field."""
    text = info.split(b"\0", 1)[0].decode("latin-1", "replace")
    text = re.sub(r"[^A-Za-z0-9._ -]", "", text).strip()
    return text if len(text) >= 3 else ""


class _Stream:
    def __init__(self, path):
        self.path = path
        self.fh = open(path, "wb")
        self.next_offset = None
        self.bytes = 0
        self.gaps = 0
        self.duplicates = 0

    def write(self, chunk):
        if self.next_offset is not None and chunk.offset < self.next_offset:
            self.duplicates += 1
            return
        if self.next_offset is not None and chunk.offset > self.next_offset:
            self.gaps += 1
        self.fh.write(chunk.data)
        self.bytes += len(chunk.data)
        self.next_offset = chunk.offset + len(chunk.data)

    def close(self):
        self.fh.close()


class _File:
    def __init__(self, ident, total, info):
        self.ident = ident
        self.total = total
        self.info = info
        self.buf = bytearray(total)
        self.have = {}  # offset -> length

    def add(self, chunk):
        if chunk.offset + len(chunk.data) > self.total:
            return
        self.buf[chunk.offset:chunk.offset + len(chunk.data)] = chunk.data
        self.have[chunk.offset] = len(chunk.data)

    def received(self):
        covered = bytearray(self.total)
        for off, n in self.have.items():
            covered[off:off + n] = b"\1" * n
        return sum(covered)

    @property
    def complete(self):
        return self.received() == self.total


class Sink:
    def __init__(self, outdir):
        self.outdir = outdir
        os.makedirs(os.path.join(outdir, "files"), exist_ok=True)
        self.streams = {}
        self.segments = []
        self.files = {}
        self.written = {}
        self.index = []

    def add(self, chunk):
        if chunk.kind == "stream":
            self._stream(chunk)
        else:
            self._file(chunk)

    def _stream(self, chunk):
        s = self.streams.get(chunk.id)
        if s is not None and s.next_offset is not None and chunk.offset + 1_000_000 < s.next_offset:
            # offset jumped far back: the stream was restarted, open a new segment
            s.close()
            s = None
        if s is None:
            n = sum(1 for seg in self.segments if seg.ident == chunk.id)
            path = os.path.join(self.outdir, f"stream_{chunk.id}_{n:03d}.mp3")
            s = self.streams[chunk.id] = _Stream(path)
            s.ident = chunk.id
            self.segments.append(s)
        s.write(chunk)

    def _file(self, chunk):
        key = (chunk.id, chunk.total, chunk.info)
        f = self.files.get(key)
        if f is None:
            f = self.files[key] = _File(chunk.id, chunk.total, chunk.info)
        f.add(chunk)
        if f.complete:
            self._write_file(f, partial=False)
            del self.files[key]

    def _write_file(self, f, partial):
        data = bytes(f.buf)
        digest = hashlib.sha1(data).hexdigest()
        if not partial and digest in self.written:
            return
        name = info_name(f.info) or f"file_{f.ident:05d}_{digest[:8]}{guess_extension(data)}"
        if partial:
            name += ".partial"
        path = os.path.join(self.outdir, "files", name)
        with open(path, "wb") as fh:
            fh.write(data)
        if not partial:
            self.written[digest] = path
        self.index.append({
            "id": f.ident,
            "size": f.total,
            "received": f.received(),
            "complete": not partial,
            "info_hex": f.info.hex(),
            "sha1": digest,
            "path": os.path.relpath(path, self.outdir),
        })

    def close(self):
        for f in list(self.files.values()):
            if f.received():
                self._write_file(f, partial=True)
        self.files.clear()
        streams = []
        for s in self.segments:
            s.close()
            streams.append({"id": s.ident, "path": os.path.relpath(s.path, self.outdir),
                            "bytes": s.bytes, "gaps": s.gaps, "duplicates": s.duplicates})
        with open(os.path.join(self.outdir, "index.json"), "w") as fh:
            json.dump({"streams": streams, "files": self.index}, fh, indent=2)
        return streams, self.index
