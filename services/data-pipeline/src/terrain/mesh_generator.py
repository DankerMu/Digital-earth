from __future__ import annotations

import gzip
import math
import struct
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

from .tile_pyramid import GeoRect


WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
WGS84_B = WGS84_A * (1.0 - WGS84_F)


def wgs84_to_ecef(
    lon_deg: float, lat_deg: float, height_m: float
) -> tuple[float, float, float]:
    lon = math.radians(float(lon_deg))
    lat = math.radians(float(lat_deg))
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)

    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    x = (n + height_m) * cos_lat * cos_lon
    y = (n + height_m) * cos_lat * sin_lon
    z = (n * (1.0 - WGS84_E2) + height_m) * sin_lat
    return x, y, z


def _transform_to_scaled_space(
    x: float, y: float, z: float
) -> tuple[float, float, float]:
    return x / WGS84_A, y / WGS84_A, z / WGS84_B


def zigzag_encode(value: int) -> int:
    v = int(value)
    if v >= 0:
        return v << 1
    return (-v << 1) - 1


def zigzag_decode(value: int) -> int:
    v = int(value)
    return (v >> 1) ^ (-(v & 1))


def delta_zigzag_encode(values: Sequence[int]) -> list[int]:
    out: list[int] = []
    prev = 0
    for v in values:
        delta = int(v) - prev
        prev = int(v)
        out.append(zigzag_encode(delta))
    return out


def delta_zigzag_decode(values: Sequence[int]) -> list[int]:
    out: list[int] = []
    acc = 0
    for v in values:
        acc += zigzag_decode(int(v))
        out.append(acc)
    return out


def high_water_mark_encode(indices: Sequence[int]) -> list[int]:
    out: list[int] = []
    highest = 0
    for idx in indices:
        code = highest - int(idx)
        if code < 0:
            raise ValueError("Indices are not suitable for high-water mark encoding")
        out.append(code)
        if code == 0:
            highest += 1
    return out


def high_water_mark_decode(codes: Sequence[int]) -> list[int]:
    out: list[int] = []
    highest = 0
    for code in codes:
        code_i = int(code)
        out.append(highest - code_i)
        if code_i == 0:
            highest += 1
    return out


@dataclass(frozen=True)
class QuantizedMeshOptions:
    gzip: bool = False
    gzip_level: int = 9


def _quantize_to_uint16(values: Iterable[int]) -> bytes:
    arr = np.asarray(list(values), dtype="<u2")
    return arr.tobytes()


def _quantize_heights(heights: np.ndarray) -> tuple[float, float, np.ndarray]:
    finite = heights[np.isfinite(heights)]
    if finite.size == 0:
        min_h = 0.0
        max_h = 0.0
    else:
        min_h = float(np.min(finite))
        max_h = float(np.max(finite))
    if max_h <= min_h:
        max_h = min_h + 1.0
    clean = np.where(np.isfinite(heights), heights, min_h).astype(np.float32)
    q = np.round((clean - min_h) / (max_h - min_h) * 32767.0).astype(np.int32)
    q = np.clip(q, 0, 32767).astype(np.int32)
    return min_h, max_h, q


def _build_grid_triangles(n: int) -> list[int]:
    indices: list[int] = []
    for j in range(n - 1):
        for i in range(n - 1):
            sw = j * n + i
            se = sw + 1
            nw = (j + 1) * n + i
            ne = nw + 1
            indices.extend([sw, se, nw, se, ne, nw])
    return indices


def _reorder_by_first_appearance(
    vertex_count: int,
    *,
    triangle_indices: Sequence[int],
    u: Sequence[int],
    v: Sequence[int],
    h: Sequence[int],
    edge_lists: Sequence[Sequence[int]],
) -> tuple[list[int], list[int], list[int], list[int], list[list[int]]]:
    old_to_new: dict[int, int] = {}
    new_to_old: list[int] = []

    def ensure(old_idx: int) -> int:
        existing = old_to_new.get(old_idx)
        if existing is not None:
            return existing
        new_idx = len(new_to_old)
        old_to_new[old_idx] = new_idx
        new_to_old.append(old_idx)
        return new_idx

    new_triangles: list[int] = []
    for old_idx in triangle_indices:
        new_triangles.append(ensure(int(old_idx)))

    if len(new_to_old) != vertex_count:
        # In a regular grid all vertices should be referenced by triangles.
        missing = vertex_count - len(new_to_old)
        raise ValueError(
            f"Mesh triangles did not reference all vertices (missing {missing})"
        )

    u_new = [int(u[old]) for old in new_to_old]
    v_new = [int(v[old]) for old in new_to_old]
    h_new = [int(h[old]) for old in new_to_old]

    edges_new: list[list[int]] = []
    for edge in edge_lists:
        edges_new.append([old_to_new[int(old)] for old in edge])

    return new_triangles, u_new, v_new, h_new, edges_new


def encode_quantized_mesh(
    rect: GeoRect,
    heights_m: np.ndarray,
    *,
    options: QuantizedMeshOptions | None = None,
) -> bytes:
    """Encode a Cesium quantized-mesh-1.0 tile (EPSG:4326, TMS)."""
    options = options or QuantizedMeshOptions()

    if heights_m.ndim != 2:
        raise ValueError("heights_m must be a 2D array")
    if heights_m.shape[0] != heights_m.shape[1]:
        raise ValueError("heights_m must be a square grid")
    n = int(heights_m.shape[0])
    if n < 2:
        raise ValueError("heights_m must be at least 2x2")

    min_h, max_h, q_heights = _quantize_heights(heights_m)

    u_abs: list[int] = []
    v_abs: list[int] = []
    h_abs: list[int] = []
    for j in range(n):
        v_q = int(round(j / (n - 1) * 32767.0))
        for i in range(n):
            u_q = int(round(i / (n - 1) * 32767.0))
            u_abs.append(u_q)
            v_abs.append(v_q)
            h_abs.append(int(q_heights[j, i]))

    vertex_count = n * n
    tri_old = _build_grid_triangles(n)

    west_edge = [j * n for j in range(n)]
    south_edge = [i for i in range(n)]
    east_edge = [j * n + (n - 1) for j in range(n)]
    north_edge = [(n - 1) * n + i for i in range(n)]

    tri, u_abs, v_abs, h_abs, edges = _reorder_by_first_appearance(
        vertex_count,
        triangle_indices=tri_old,
        u=u_abs,
        v=v_abs,
        h=h_abs,
        edge_lists=[west_edge, south_edge, east_edge, north_edge],
    )
    west_edge_new, south_edge_new, east_edge_new, north_edge_new = edges

    u_enc = delta_zigzag_encode(u_abs)
    v_enc = delta_zigzag_encode(v_abs)
    h_enc = delta_zigzag_encode(h_abs)

    tri_codes = high_water_mark_encode(tri)

    triangle_count = len(tri) // 3

    center_lon = (rect.west + rect.east) / 2.0
    center_lat = (rect.south + rect.north) / 2.0
    center_height = (min_h + max_h) / 2.0
    center_x, center_y, center_z = wgs84_to_ecef(center_lon, center_lat, center_height)

    corners = [
        (rect.west, rect.south),
        (rect.east, rect.south),
        (rect.west, rect.north),
        (rect.east, rect.north),
    ]
    max_radius = 0.0
    for lon, lat in corners:
        for h in (min_h, max_h):
            x, y, z = wgs84_to_ecef(lon, lat, h)
            dx = x - center_x
            dy = y - center_y
            dz = z - center_z
            max_radius = max(max_radius, math.sqrt(dx * dx + dy * dy + dz * dz))

    bs_center_x, bs_center_y, bs_center_z = center_x, center_y, center_z
    bs_radius = max_radius

    hoc_x, hoc_y, hoc_z = _transform_to_scaled_space(center_x, center_y, center_z)

    header = struct.pack(
        "<dddffddddddd",
        float(center_x),
        float(center_y),
        float(center_z),
        float(min_h),
        float(max_h),
        float(bs_center_x),
        float(bs_center_y),
        float(bs_center_z),
        float(bs_radius),
        float(hoc_x),
        float(hoc_y),
        float(hoc_z),
    )

    parts: list[bytes] = [header, struct.pack("<I", vertex_count)]
    parts.append(_quantize_to_uint16(u_enc))
    parts.append(_quantize_to_uint16(v_enc))
    parts.append(_quantize_to_uint16(h_enc))

    raw = b"".join(parts)

    # Align to 2-byte boundary for IndexData16.
    if len(raw) % 2 != 0:
        raw += b"\x00"

    raw += struct.pack("<I", triangle_count)
    raw += _quantize_to_uint16(tri_codes)

    def _write_edge(edge_indices: Sequence[int], buf: bytes) -> bytes:
        buf += struct.pack("<I", len(edge_indices))
        buf += _quantize_to_uint16(edge_indices)
        return buf

    raw = _write_edge(west_edge_new, raw)
    raw = _write_edge(south_edge_new, raw)
    raw = _write_edge(east_edge_new, raw)
    raw = _write_edge(north_edge_new, raw)

    if options.gzip:
        return gzip.compress(raw, compresslevel=int(options.gzip_level))
    return raw
