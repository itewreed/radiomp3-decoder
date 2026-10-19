"""Software teletext slicer for raw VBI sample dumps.

The original player read raw BT848 VBI samples (2044 per line, 16 lines per
field) and recovered the bits itself. This slicer does the same job for raw
8-bit dumps, e.g. from Linux bttv (/dev/vbi, 2048 samples per line at
35.468950 MHz for PAL) or other capture tools. For VHS tapes, use
vhs-teletext instead and feed its .t42 output to the decoder.
"""

import numpy as np

TELETEXT_RATE = 6_937_500.0
RUNIN = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
FRAMING = [1, 1, 1, 0, 0, 1, 0, 0]  # 0x27, LSB first


def slice_line(line, samples_per_bit, search=None, step=0.25):
    """Return the 42 data bytes of one VBI line, or None."""
    s = np.asarray(line, dtype=np.float32)
    n_bits = 24 + 42 * 8
    span = n_bits * samples_per_bit
    if search is None:
        search = max(1.0, len(s) - span - 1)
    starts = np.arange(0, min(search, len(s) - span - 1), step, dtype=np.float32)
    if len(starts) == 0:
        return None
    # threshold from the run-in region
    window = s[: int(min(len(s), search + 24 * samples_per_bit))]
    lo, hi = np.percentile(window, 5), np.percentile(window, 95)
    if hi - lo < 8:
        return None
    thr = (hi + lo) / 2.0
    pos = starts[:, None] + (np.arange(24, dtype=np.float32) + 0.5) * samples_per_bit
    bits = (np.interp(pos, np.arange(len(s)), s) > thr).astype(np.int8)
    want = np.array(RUNIN + FRAMING, dtype=np.int8)
    score = (bits == want).sum(axis=1)
    frame_ok = (bits[:, 16:] == want[16:]).all(axis=1)
    score = np.where(frame_ok, score, -1)
    top = score.max()
    if top < 20:
        return None
    # centre of the best-matching phase range
    start = float(np.median(starts[score == top]))
    pos = start + (np.arange(24, n_bits, dtype=np.float32) + 0.5) * samples_per_bit
    data_bits = (np.interp(pos, np.arange(len(s)), s) > thr).astype(np.uint8)
    data_bits = data_bits.reshape(42, 8)
    weights = (1 << np.arange(8)).astype(np.uint8)
    return bytes((data_bits * weights).sum(axis=1).astype(np.uint8))


def read_raw_vbi(path, samples_per_line=2048, sampling_rate=35_468_950.0, offset=0):
    """Yield 42-byte packets from a raw 8-bit VBI dump."""
    spb = sampling_rate / TELETEXT_RATE
    raw = np.fromfile(path, dtype=np.uint8, offset=offset)
    lines = raw[: len(raw) // samples_per_line * samples_per_line].reshape(-1, samples_per_line)
    search = min(samples_per_line // 3, samples_per_line - int(370 * spb) - 2)
    for line in lines:
        pk = slice_line(line, spb, search=search)
        if pk is not None:
            yield pk


def render_line(packet, samples_per_line=2048, sampling_rate=35_468_950.0,
                start=120.0, low=40, high=200, noise=0.0, rng=None):
    """Synthesize one raw VBI line for a packet (for tests)."""
    spb = sampling_rate / TELETEXT_RATE
    bits = RUNIN + FRAMING + [(b >> i) & 1 for b in packet for i in range(8)]
    t = np.arange(samples_per_line, dtype=np.float32)
    idx = np.floor((t - start) / spb).astype(int)
    level = np.full(samples_per_line, float(low), dtype=np.float32)
    valid = (idx >= 0) & (idx < len(bits))
    level[valid] = np.where(np.array(bits)[idx[valid]] == 1, high, low)
    # soften the edges a little like a real channel
    kernel = np.ones(3, dtype=np.float32) / 3
    level = np.convolve(level, kernel, mode="same")
    if noise:
        rng = rng or np.random.default_rng(0)
        level = level + rng.normal(0, noise, samples_per_line)
    return np.clip(level, 0, 255).astype(np.uint8)
