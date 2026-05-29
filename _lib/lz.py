"""LZ decompressor for the pokeprism LZ format.

This is a Python port of `home/decompress.asm`. The format spec is in the
asm comments (lines 44-91). Summary:

A command byte:
    %CCCNNNNN
        C: 3-bit command (bits 5-7)
        N: 5-bit length-1 (bits 0-4) — so N=0 means 1, N=31 means 32

Commands:
    0  LZ_DATA          — copy next n bytes literally
    1  LZ_REPEAT_1      — repeat next byte n times
    2  LZ_REPEAT_2      — alternate next 2 bytes n times
    3  LZ_ZERO          — write zero n times
    4  LZ_COPY_NORMAL   — copy n bytes from offset (output history)
    5  LZ_COPY_FLIPPED  — same, but bit-reverse each byte
    6  LZ_COPY_REVERSED — same, but copy bytes in reverse order
    7  LZ_LONG          — extends length to 10 bits, re-parses command

For LZ_LONG: the original command byte becomes:
    %111xxxyy yyyyyyyy
        x: new 3-bit command (the actual op)
        y: 10-bit length-1

For COPY_* commands, the offset is encoded in the next 1 or 2 bytes:
    - If first byte's bit 7 is set: relative. e = bits 0-6 of the byte;
      offset = -(0x80 - bits)  ≡  cpl; sub $80 in asm.
      So 0x80 → -1, 0x81 → -2, ... 0xFF → -128.
      Only 1 byte consumed.
    - Otherwise: absolute. (byte1 << 8) | byte2 is an absolute 16-bit
      offset into the output (from byte 0). Two bytes consumed.

Stream is terminated by 0xFF as a command byte.
"""

from __future__ import annotations


LZ_END = 0xFF


def decompress(data: bytes, offset: int = 0) -> tuple[bytes, int]:
    """Decompress an LZ-compressed byte stream.

    Returns (decompressed_bytes, bytes_consumed). Bytes consumed includes
    the terminating 0xFF, so caller can advance to the next stream.
    """
    out = bytearray()
    i = offset

    while True:
        if i >= len(data):
            raise ValueError("unexpected end of LZ stream (no $FF terminator)")
        cmd_byte = data[i]
        i += 1

        if cmd_byte == LZ_END:
            break

        if (cmd_byte & 0xE0) == 0xE0:
            # LZ_LONG: 10-bit length, new command in bits 2-4.
            cmd = (cmd_byte >> 2) & 0x07
            length_hi = cmd_byte & 0x03
            if i >= len(data):
                raise ValueError("truncated LZ_LONG length")
            length = ((length_hi << 8) | data[i]) + 1
            i += 1
        else:
            cmd = (cmd_byte >> 5) & 0x07
            length = (cmd_byte & 0x1F) + 1

        if cmd == 0:  # LZ_DATA: literal
            out += data[i : i + length]
            i += length

        elif cmd == 1:  # LZ_REPEAT_1
            out += bytes([data[i]]) * length
            i += 1

        elif cmd == 2:  # LZ_REPEAT_2
            a, b = data[i], data[i + 1]
            i += 2
            out += bytes(a if k & 1 == 0 else b for k in range(length))

        elif cmd == 3:  # LZ_ZERO
            out += bytes(length)

        elif cmd in (4, 5, 6):  # LZ_COPY_*
            byte1 = data[i]
            i += 1
            if byte1 & 0x80:
                # Relative offset: -(0x80 - (byte1 & 0x7F)) from current pos
                # Reproduces the asm: cpl ($FF xor byte1) then sub $80.
                # ((~byte1) & 0xFF) - 0x80 → signed 16-bit, negative.
                neg = ((~byte1) & 0xFF) - 0x80
                # neg is in -128..-1. Add to current output length.
                src = len(out) + neg
            else:
                byte2 = data[i]
                i += 1
                src = (byte1 << 8) | byte2

            if src < 0 or src > len(out):
                raise ValueError(
                    f"copy source out of range: src={src}, out_len={len(out)}, "
                    f"offset in stream={i - 2:#x}"
                )

            if cmd == 4:  # LZ_COPY_NORMAL
                # NB: src may equal len(out), in which case the copy reads
                # bytes being written — preserve asm semantics (read [de],
                # write [hli], inc de).
                for _ in range(length):
                    out.append(out[src])
                    src += 1

            elif cmd == 5:  # LZ_COPY_FLIPPED
                for _ in range(length):
                    out.append(_bit_reverse(out[src]))
                    src += 1

            elif cmd == 6:  # LZ_COPY_REVERSED
                for _ in range(length):
                    out.append(out[src])
                    src -= 1

        else:
            raise ValueError(f"impossible LZ command {cmd}")

    return bytes(out), i - offset


def _bit_reverse(b: int) -> int:
    """Reverse the 8 bits of `b`. Matches the asm bit-flip routine."""
    b = ((b & 0xF0) >> 4) | ((b & 0x0F) << 4)
    b = ((b & 0xCC) >> 2) | ((b & 0x33) << 2)
    b = ((b & 0xAA) >> 1) | ((b & 0x55) << 1)
    return b
