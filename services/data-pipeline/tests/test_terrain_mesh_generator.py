from __future__ import annotations

import struct

import numpy as np
import pytest

from terrain.mesh_generator import (
    QuantizedMeshOptions,
    delta_zigzag_decode,
    delta_zigzag_encode,
    encode_quantized_mesh,
    high_water_mark_decode,
    high_water_mark_encode,
    wgs84_to_ecef,
    zigzag_decode,
    zigzag_encode,
)
from terrain.tile_pyramid import GeoRect


def test_zigzag_roundtrip() -> None:
    for v in (-10, -1, 0, 1, 10, 12345, -12345):
        assert zigzag_decode(zigzag_encode(v)) == v


def test_delta_zigzag_roundtrip() -> None:
    values = [0, 1, 1, 3, 2, 10, 10]
    encoded = delta_zigzag_encode(values)
    decoded = delta_zigzag_decode(encoded)
    assert decoded == values


def test_high_water_mark_roundtrip() -> None:
    indices = [0, 1, 2, 2, 1, 0, 3, 0]
    codes = high_water_mark_encode(indices)
    assert high_water_mark_decode(codes) == indices

    with pytest.raises(ValueError):
        high_water_mark_encode([0, 2])


def test_wgs84_to_ecef_axis_points() -> None:
    x, y, z = wgs84_to_ecef(0.0, 0.0, 0.0)
    assert x == pytest.approx(6378137.0, abs=1e-3)
    assert y == pytest.approx(0.0, abs=1e-3)
    assert z == pytest.approx(0.0, abs=1e-3)

    x, y, z = wgs84_to_ecef(90.0, 0.0, 0.0)
    assert x == pytest.approx(0.0, abs=1e-3)
    assert y == pytest.approx(6378137.0, abs=1e-3)
    assert z == pytest.approx(0.0, abs=1e-3)


def _read_u16(buf: bytes, offset: int, count: int) -> tuple[list[int], int]:
    end = offset + count * 2
    values = list(np.frombuffer(buf[offset:end], dtype="<u2"))
    return values, end


def test_encode_quantized_mesh_basic_decode() -> None:
    rect = GeoRect(west=0.0, south=0.0, east=1.0, north=1.0)
    heights = np.array(
        [
            [0.0, 10.0, 20.0],
            [30.0, 40.0, 50.0],
            [60.0, 70.0, 80.0],
        ],
        dtype=np.float32,
    )

    payload = encode_quantized_mesh(rect, heights, options=QuantizedMeshOptions(gzip=False))
    assert len(payload) > 88

    # Header: <dddffddddddd
    (
        _cx,
        _cy,
        _cz,
        min_h,
        max_h,
        _bsx,
        _bsy,
        _bsz,
        _bsr,
        _hox,
        _hoy,
        _hoz,
    ) = struct.unpack("<dddffddddddd", payload[:88])
    assert min_h == pytest.approx(0.0)
    assert max_h == pytest.approx(80.0)

    vertex_count = struct.unpack("<I", payload[88:92])[0]
    assert vertex_count == 9
    offset = 92

    u_enc, offset = _read_u16(payload, offset, vertex_count)
    v_enc, offset = _read_u16(payload, offset, vertex_count)
    h_enc, offset = _read_u16(payload, offset, vertex_count)

    u = delta_zigzag_decode(u_enc)
    v = delta_zigzag_decode(v_enc)
    h = delta_zigzag_decode(h_enc)
    assert min(u) == 0
    assert max(u) == 32767
    assert min(v) == 0
    assert max(v) == 32767
    assert min(h) == 0
    assert max(h) == 32767

    if offset % 2 != 0:
        offset += 1
    triangle_count = struct.unpack("<I", payload[offset : offset + 4])[0]
    offset += 4
    assert triangle_count == 8  # 2*(n-1)^2 where n=3

    tri_codes, offset = _read_u16(payload, offset, triangle_count * 3)
    tri = high_water_mark_decode(tri_codes)
    assert len(tri) == triangle_count * 3
    assert min(tri) >= 0
    assert max(tri) < vertex_count

    # Edge lists: 4x (count + indices)
    for expected_edge_len in (3, 3, 3, 3):
        edge_count = struct.unpack("<I", payload[offset : offset + 4])[0]
        offset += 4
        assert edge_count == expected_edge_len
        edge, offset = _read_u16(payload, offset, edge_count)
        assert min(edge) >= 0
        assert max(edge) < vertex_count


def test_encode_quantized_mesh_gzip_magic() -> None:
    rect = GeoRect(west=0.0, south=0.0, east=1.0, north=1.0)
    heights = np.zeros((2, 2), dtype=np.float32)
    payload = encode_quantized_mesh(rect, heights, options=QuantizedMeshOptions(gzip=True))
    assert payload[:2] == b"\x1f\x8b"
