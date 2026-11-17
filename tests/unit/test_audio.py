"""Audio conversion tests. The table is derived, so these numbers are the proof.

Known G.711 reference points, using the reference `ulaw2linear` from Sun's
g711.c (sign bit set means negative): 0xFF and 0x7F decode to 0, 0x00 to
-32124, 0x80 to +32124.
"""

from __future__ import annotations

import base64
import struct

import pytest

from media.audio import (
    FRAME_BYTES,
    ULAW_TO_PCM16,
    decode_twilio_media,
    mulaw_frame_to_pcm16,
    pcm16_to_ulaw,
    ulaw_to_pcm16,
)


def test_table_is_symmetric_around_zero() -> None:
    assert ULAW_TO_PCM16[0xFF] == 0
    assert ULAW_TO_PCM16[0x7F] == 0
    assert ULAW_TO_PCM16[0x00] == -32124
    assert ULAW_TO_PCM16[0x80] == 32124


def test_ulaw_to_pcm16_doubles_the_length() -> None:
    pcm = ulaw_to_pcm16(bytes([0xFF, 0x00, 0x80]))
    assert len(pcm) == 6
    assert struct.unpack("<hhh", pcm) == (0, -32124, 32124)


def test_round_trip_stays_within_quantisation_error() -> None:
    original = [0, 100, -100, 1000, -1000, 8000, -8000, 32000, -32000]
    pcm = b"".join(struct.pack("<h", sample) for sample in original)
    restored = ulaw_to_pcm16(pcm16_to_ulaw(pcm))
    samples = struct.unpack("<" + "h" * len(original), restored)
    for source, result in zip(original, samples, strict=True):
        # one mu-law step at 8 kHz is 2 % of full scale at worst
        assert abs(source - result) <= max(256, abs(source) // 8), (source, result)


def test_a_twilio_frame_is_160_bytes() -> None:
    assert FRAME_BYTES == 160


def test_twilio_media_decodes_to_one_pcm_frame() -> None:
    ulaw = bytes([0xFF] * FRAME_BYTES)
    payload = base64.b64encode(ulaw).decode()
    pcm = mulaw_frame_to_pcm16(payload)
    assert len(pcm) == FRAME_BYTES * 2
    assert pcm == b"\x00\x00" * FRAME_BYTES


def test_empty_media_is_refused() -> None:
    with pytest.raises(ValueError):
        decode_twilio_media("")
    with pytest.raises(ValueError):
        pcm16_to_ulaw(b"\x01")
