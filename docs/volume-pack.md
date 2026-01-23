<!--
  Volume Pack format (ST-0139 / Issue #170)

  This document defines a small, forward-compatible container for volumetric raster
  data used by Digital Earth clients and pipeline services.
-->

# Volume Pack Binary Format (VOLP)

Volume Pack is a binary container with a small JSON header followed by a compressed
payload (body). The header is designed to be **forward-compatible**: decoders must
ignore unknown header fields.

## 1) Binary layout

All integer fields in the fixed prefix are **little-endian**.

```
+----------------+------------------+----------------+
| Magic (4 bytes)| Header Len (4B)  | Header (JSON)  |
+----------------+------------------+----------------+
|            Body (zstd compressed data)            |
+---------------------------------------------------+
```

- **Magic**: 4 ASCII bytes: `VOLP`
- **Header Len**: `uint32` length (bytes) of the UTF-8 JSON header
- **Header**: UTF-8 JSON bytes (no NUL terminator)
- **Body**: zstd frame containing the raw tensor bytes

## 2) Header JSON

Minimum required fields for decoding:

- `version` (number): Header schema version. Current version is `1`.
- `shape` (array of 3 integers): `[levels, lat, lon]`
- `dtype` (string): element type (see “Supported dtypes”)
- `compression` (string): must be `"zstd"`
- `scale` (number): scale factor (see below)
- `offset` (number): offset (see below)

Common metadata fields:

- `bbox` (object): `{ west, south, east, north, bottom, top }`
- `levels` (array): vertical coordinate values aligned to the first dimension
- `variable` (string)
- `valid_time` (string, ISO8601 UTC)

Example:

```json
{
  "version": 1,
  "bbox": { "west": -180, "south": -90, "east": 180, "north": 90, "bottom": 1000, "top": 100 },
  "shape": [32, 64, 64],
  "dtype": "float32",
  "scale": 1.0,
  "offset": 0.0,
  "compression": "zstd",
  "levels": [1000, 925, 850],
  "variable": "cloud_density",
  "valid_time": "2026-01-01T00:00:00Z"
}
```

## 3) Body: tensor bytes

After zstd decompression, the body is a dense tensor stored in **C-order** (row-major)
with the header `shape`:

`index = ((level * lat + y) * lon + x)`

All multi-byte dtypes are stored as **little-endian**.

### Supported dtypes (v1 reference)

Implementations may support a subset; servers should emit common types:

- `uint8`
- `int16`
- `int32`
- `float32`
- `float64`

## 4) Scale/offset semantics

The header `scale`/`offset` define a linear transform from stored values to physical
values:

`physical = stored * scale + offset`

For unscaled floats, use `scale = 1.0` and `offset = 0.0`.

## 5) Defensive limits

Implementations use conservative size limits to reduce denial-of-service risk when
decoding untrusted payloads:

- **Max header bytes**: `1 MiB` (1,048,576 bytes). `Header Len` must be `>= 1` and
  `<= 1 MiB`.
- **Max body bytes (decoded)**: `256 MiB` (268,435,456 bytes). The decoded body must
  match `shape[0] * shape[1] * shape[2] * bytesPerElement(dtype)` and must be
  `<= 256 MiB`.
- **Default scale/offset**: if missing or invalid, decoders use `scale = 1.0` and
  `offset = 0.0`.

## 6) Versioning & compatibility rules

- The fixed binary prefix (`VOLP` + header length + JSON header) is intended to stay
  stable across header schema versions.
- Decoders must:
  - ignore unknown header keys
  - treat missing `version` as `1` (best-effort)
  - reject unknown `compression` values
- If a future change requires a breaking binary layout, it must use a **different**
  4-byte magic value so old clients fail fast with a clear “unknown format” error.

## 7) Reference implementations

- Python encoder/decoder: `services/data-pipeline/src/volume/pack.py`
- TypeScript decoder: `apps/web/src/lib/volumePack.ts`
