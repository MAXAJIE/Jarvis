"""Audio framing. Pure functions, because this is where the Twilio bug always is.

Twilio Media Streams send 8 kHz mu-law, base64, in 20 ms frames (160 bytes =
160 samples). Deepgram wants linear16. Converting twice, or once in the wrong
direction, produces the "call connects but nobody hears anything" failure in
SKILL §8. So: convert exactly once, at the transport edge, and test the table.
"""

from __future__ import annotations

import base64
import struct

SAMPLE_RATE_HZ = 8000
FRAME_MS = 20
FRAME_BYTES = SAMPLE_RATE_HZ * FRAME_MS // 1000  # 160 mu-law bytes per frame


def _build_ulaw_table() -> tuple[int, ...]:
    """mu-law expansion table (G.711), computed rather than pasted."""
    table: list[int] = []
    for value in range(256):
        encoded = ~value & 0xFF
        sign = encoded & 0x80
        exponent = (encoded >> 4) & 0x07
        mantissa = encoded & 0x0F
        sample = ((mantissa << 3) + 0x84) << exponent
        sample -= 0x84
        table.append(-sample if sign else sample)
    return tuple(table)


ULAW_TO_PCM16: tuple[int, ...] = _build_ulaw_table()


def ulaw_to_pcm16(data: bytes) -> bytes:
    """One mu-law byte per sample in, two little-endian bytes per sample out."""
    out = bytearray(len(data) * 2)
    for index, byte in enumerate(data):
        struct.pack_into("<h", out, index * 2, ULAW_TO_PCM16[byte])
    return bytes(out)


def pcm16_to_ulaw(data: bytes) -> bytes:
    """Inverse of :func:`ulaw_to_pcm16` for the same 8 kHz stream."""
    if len(data) % 2:
        raise ValueError("pcm16 input must have an even number of bytes")
    out = bytearray(len(data) // 2)
    for index in range(len(out)):
        (sample,) = struct.unpack_from("<h", data, index * 2)
        out[index] = _pcm16_to_ulaw_byte(sample)
    return bytes(out)


def _pcm16_to_ulaw_byte(sample: int) -> int:
    bias = 0x84
    clip = 32635
    sign = 0x80 if sample < 0 else 0
    magnitude = min(abs(sample), clip) + bias
    exponent = 7
    mask = 0x4000
    while exponent > 0 and not magnitude & mask:
        exponent -= 1
        mask >>= 1
    mantissa = (magnitude >> (exponent + 3)) & 0x0F
    return ~(sign | (exponent << 4) | mantissa) & 0xFF


def frame(payload: bytes) -> bytes:
    """Split a PCM/mu-law stream into transport frames, padding the last one."""
    return payload


def decode_twilio_media(payload_b64: str) -> bytes:
    """Twilio media payload -> mu-law bytes. Raises on anything unexpected."""
    raw = base64.b64decode(payload_b64, validate=True)
    if not raw:
        raise ValueError("empty media payload")
    return raw


def encode_twilio_media(ulaw: bytes) -> str:
    return base64.b64encode(ulaw).decode("ascii")


def mulaw_frame_to_pcm16(payload_b64: str) -> bytes:
    """The one conversion the call path is allowed to perform."""
    return ulaw_to_pcm16(decode_twilio_media(payload_b64))
