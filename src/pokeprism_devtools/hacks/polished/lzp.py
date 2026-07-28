"""Decompress polished's `.ablk.lzp` block codec — a superset of Gen-2 LZ.

Polished compresses its map block data with its own tool (`tools/lzpcompress.c`)
and INCBINs the result (`data/maps/blocks.asm` → `maps/X.ablk.lzp`). The game
decodes it at load with the routine in `home/decompress.asm`, which is stock
pokecrystal's LZ (the same one `shared.lz` ports) with three deliberate
extensions — so the shared decompressor cannot read it, and this one, on
polished's side of the seam, can.

The three differences from `shared.lz`, each re-derived from `home/decompress.asm`
and cross-checked against the compressor's own `--uncompress` model:

  - **REPEAT and ALTERNATE carry a per-command length minimum.** A run's length
    is `field + minimum`, where the minimum is 2 for REPEAT and 3 for ALTERNATE
    (a 1-byte "repeat" or 2-byte "alternate" would just be literal data, so those
    encodings are spent on longer runs). DATA, ZERO and the COPY family keep the
    stock `+1`. See `.lz_iterate` (one pre-write before the fill) and
    `.lz_alternate` (two) in the asm, and `minimum_count` in the tool.
  - **Three extended opcodes**, `$fc`/`$fd`/`$fe`, each `db subtype` then a
    length byte (count = `lenbyte + 1`, 1..256) and `ceil(count/2)` payload
    bytes of packed nibbles:
      - `$fc` packhi0 — each payload byte P emits `(P & $f0)` then `(P & $0f) << 4`;
      - `$fd` pack16  — emits `table[P >> 4]` then `table[P & $0f]`, the fixed
        16-byte dictionary the asm carries at `.pack16_table`;
      - `$fe` packlo0 — emits `(P >> 4)` then `(P & $0f)`.
  - Those opcodes live in the `$fc-$ff` range that would otherwise decode as
    LZ_LONG, so LONG-normal must exclude them (and `$ff` stays the terminator).

Everything else — the 3-bit command / 5-bit length byte, LZ_LONG's 10-bit
length, the COPY offset encoding (relative negative in one byte, 15-bit absolute
in two) and bit-flipped / reversed copies — is stock, and read the same way here.
"""

from __future__ import annotations

LZ_END = 0xFF

#: Output length is `field + MINIMUM[command]`. REPEAT/ALTERNATE spend their
#: shortest encodings on longer runs (a 1-byte repeat is just a literal); the
#: rest match stock's `+1`. Mirrors `minimum_count` in `tools/lzpcompress.c`.
_MINIMUM = (1, 2, 3, 1, 1, 1, 1)  # DATA, REPEAT, ALTERNATE, ZERO, COPY x3

#: The 16-byte dictionary the `$fd` pack16 opcode indexes, biased toward the
#: commonest tile/bitmask bytes (`.pack16_table` in `home/decompress.asm`).
_PACK16_TABLE = (
    0x00, 0xFF, 0x01, 0x02, 0x03, 0xFE, 0x80, 0x07,
    0xC0, 0x7F, 0x04, 0x0F, 0x1F, 0x3F, 0x08, 0xFC,
)


def decompress(data: bytes, offset: int = 0) -> tuple[bytes, int]:
    """Decompress an lzp stream at `data[offset:]`.

    Returns `(decompressed_bytes, bytes_consumed)`; the consumed count includes
    the terminating `$ff`, so a caller can advance to whatever follows — the same
    contract as `shared.lz.decompress`.
    """
    out = bytearray()
    i = offset

    while True:
        if i >= len(data):
            raise ValueError("unexpected end of lzp stream (no $FF terminator)")
        b0 = data[i]
        i += 1

        if b0 == LZ_END:
            break

        # Extended opcodes $fc-$fe: a length byte, then ceil(count/2) packed
        # bytes. $ff is caught above, so the mask only matches the three.
        if (b0 & 0xFC) == 0xFC:
            length = data[i] + 1
            i += 1
            payload = (length + 1) // 2
            chunk = data[i : i + payload]
            if len(chunk) < payload:
                raise ValueError("truncated lzp extended-opcode payload")
            i += payload
            out += _unpack(b0 & 0x03, chunk, length)
            continue

        if (b0 >> 5) == 7:  # LZ_LONG: new command in bits 2-4, 10-bit length
            cmd = (b0 >> 2) & 0x07
            if i >= len(data):
                raise ValueError("truncated lzp LZ_LONG length")
            length = (((b0 & 0x03) << 8) | data[i]) + _MINIMUM[cmd]
            i += 1
        else:
            cmd = b0 >> 5
            length = (b0 & 0x1F) + _MINIMUM[cmd]

        if cmd == 0:  # LZ_DATA: literal run
            out += data[i : i + length]
            i += length
        elif cmd == 1:  # LZ_REPEAT: one byte, `length` times
            out += bytes([data[i]]) * length
            i += 1
        elif cmd == 2:  # LZ_ALTERNATE: two bytes, alternating, `length` total
            a, b = data[i], data[i + 1]
            i += 2
            out += bytes(a if k % 2 == 0 else b for k in range(length))
        elif cmd == 3:  # LZ_ZERO
            out += bytes(length)
        else:  # LZ_COPY_NORMAL / FLIPPED / REVERSED (4/5/6)
            i = _copy(out, data, i, cmd, length)

    return bytes(out), i - offset


def _unpack(subtype: int, payload: bytes, length: int) -> bytearray:
    """Expand one extended-opcode payload to `length` output bytes.

    Each payload byte carries two nibbles; the subtype decides how a nibble
    becomes a byte. `length` may be odd, in which case the final byte's low
    nibble is unused (the asm stops on the count, not the payload).
    """
    out = bytearray()
    for p in payload:
        hi, lo = p >> 4, p & 0x0F
        if subtype == 0:      # packhi0
            first, second = p & 0xF0, lo << 4
        elif subtype == 1:    # pack16
            first, second = _PACK16_TABLE[hi], _PACK16_TABLE[lo]
        else:                 # packlo0 (subtype 2)
            first, second = hi, lo
        out.append(first)
        if len(out) < length:
            out.append(second)
        if len(out) >= length:
            break
    return out


def _copy(out: bytearray, data: bytes, i: int, cmd: int, length: int) -> int:
    """Apply a COPY command that reuses `length` bytes of prior output.

    The offset is one byte when its top bit is set (a small negative offset from
    the current position) or two bytes for a 15-bit absolute offset from the
    output start — exactly `shared.lz`'s encoding. Returns the new stream index.
    """
    byte1 = data[i]
    i += 1
    if byte1 & 0x80:
        src = len(out) + (((~byte1) & 0xFF) - 0x80)  # cpl; sub $80 → -1..-128
    else:
        src = (byte1 << 8) | data[i]
        i += 1
    if src < 0 or src > len(out):
        raise ValueError(f"lzp copy source out of range: src={src}, out={len(out)}")

    if cmd == 4:      # LZ_COPY_NORMAL
        for _ in range(length):
            out.append(out[src])
            src += 1
    elif cmd == 5:    # LZ_COPY_FLIPPED
        for _ in range(length):
            out.append(_flip_bits(out[src]))
            src += 1
    else:             # LZ_COPY_REVERSED (6)
        for _ in range(length):
            out.append(out[src])
            src -= 1
    return i


def _flip_bits(b: int) -> int:
    """Reverse the 8 bits of `b` — the bit-flipped copy the asm's flip loop does."""
    b = ((b & 0xF0) >> 4) | ((b & 0x0F) << 4)
    b = ((b & 0xCC) >> 2) | ((b & 0x33) << 2)
    b = ((b & 0xAA) >> 1) | ((b & 0x55) << 1)
    return b
