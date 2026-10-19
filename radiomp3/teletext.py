"""Teletext layer: 42-byte packets -> 896-byte data pages -> superblocks.

Layout of one data page (all in magazine 8, coded as magazine bits 0):

    packet 0       ordinary page header (page number and subcode, ignored)
    packet 1       H(row index 1..15), H(aux), 38 payload bytes
    packet 2..23   H(row index), 39 payload bytes

38 + 22 * 39 = 896 bytes per page. Fifteen pages with row index 1..15
form one superblock (13 data rows + 2 parity rows).
"""

from dataclasses import dataclass, field

from . import hamming

PACKET_SIZE = 42
ROW_SIZE = 896
ROWS = 15
DATA_ROWS = 13
MAGAZINE = 0  # magazine 8 as coded in the MRAG
P1_PAYLOAD = 38
PN_PAYLOAD = 39
LAST_PACKET = 23


def payload_offset(packet):
    return 0 if packet == 1 else P1_PAYLOAD + (packet - 2) * PN_PAYLOAD


def payload_size(packet):
    return P1_PAYLOAD if packet == 1 else PN_PAYLOAD


@dataclass
class Page:
    row: int = None
    aux: int = None
    data: bytearray = field(default_factory=lambda: bytearray(ROW_SIZE))
    packets: set = field(default_factory=set)

    @property
    def complete(self):
        return len(self.packets) == LAST_PACKET  # packets 1..23

    def missing_ranges(self):
        """Byte ranges inside the 896-byte row that never arrived."""
        out = []
        for p in range(1, LAST_PACKET + 1):
            if p not in self.packets:
                start = payload_offset(p)
                out.append((start, start + payload_size(p)))
        return out


@dataclass
class Superblock:
    pages: dict = field(default_factory=dict)  # row index -> Page
    aux: int = None

    @property
    def last_row(self):
        return max(self.pages) if self.pages else 0


@dataclass
class TeletextStats:
    packets: int = 0
    other_magazine: int = 0
    bad_address: int = 0
    bad_row_index: int = 0
    pages: int = 0
    incomplete_pages: int = 0
    superblocks: int = 0


class PageAssembler:
    """Collects packets into pages and pages into superblocks.

    The original player insisted on strictly consecutive packets and threw a
    page away at the first gap. This assembler places every packet by its own
    row index, so a lost line only leaves a hole that the FEC can fill.
    """

    def __init__(self, correct_hamming=True):
        self.correct = correct_hamming
        self.stats = TeletextStats()
        self.page = None
        self.sb = Superblock()

    def feed(self, packet):
        """Feed one 42-byte packet. Returns a list of finished superblocks."""
        self.stats.packets += 1
        out = []
        addr = hamming.decode_mrag(packet[0], packet[1], self.correct)
        if addr is None:
            self.stats.bad_address += 1
            return out
        magazine, number = addr
        if magazine != MAGAZINE:
            self.stats.other_magazine += 1
            return out
        if number == 0:
            out += self._close_page()
            self.page = Page()
            return out
        if number > LAST_PACKET:
            return out
        row = hamming.decode(packet[2], self.correct)
        if row is None or not 1 <= row <= ROWS:
            self.stats.bad_row_index += 1
            return out
        if self.page is None:
            self.page = Page()
        if self.page.row is not None and self.page.row != row:
            # header lost: a new page has started
            out += self._close_page()
            self.page = Page()
        self.page.row = row
        if number == 1:
            self.page.aux = hamming.decode(packet[3], self.correct)
            body = packet[4:4 + P1_PAYLOAD]
        else:
            body = packet[3:3 + PN_PAYLOAD]
        start = payload_offset(number)
        self.page.data[start:start + len(body)] = body
        self.page.packets.add(number)
        if number == LAST_PACKET:
            out += self._close_page()
        return out

    def flush(self):
        out = self._close_page()
        out += self._close_superblock()
        return out

    def _close_page(self):
        page, self.page = self.page, None
        if page is None or page.row is None or not page.packets:
            return []
        self.stats.pages += 1
        if not page.complete:
            self.stats.incomplete_pages += 1
        out = []
        if page.row <= self.sb.last_row:
            out += self._close_superblock()
        self.sb.pages[page.row] = page
        if page.row == 1:
            self.sb.aux = page.aux
        if page.row == ROWS:
            out += self._close_superblock()
        return out

    def _close_superblock(self):
        sb, self.sb = self.sb, Superblock()
        if not sb.pages:
            return []
        self.stats.superblocks += 1
        return [sb]


def read_t42(path):
    """Yield 42-byte packets from a .t42 file (as written by vhs-teletext)."""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(PACKET_SIZE)
            if len(chunk) < PACKET_SIZE:
                return
            yield chunk
