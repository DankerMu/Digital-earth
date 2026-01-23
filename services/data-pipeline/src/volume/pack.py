from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import numpy as np
import zstandard as zstd

MAGIC: Final[bytes] = b"VOLP"
_HEADER_LEN: Final[struct.Struct] = struct.Struct("<I")

# Defensive limits: headers should be tiny (JSON metadata), and bodies are bounded
# by the declared shape+dtype for decoding.
MAX_HEADER_BYTES: Final[int] = 1024 * 1024  # 1 MiB

_SUPPORTED_DTYPES: Final[dict[str, np.dtype]] = {
    "uint8": np.dtype("uint8"),
    "int16": np.dtype("<i2"),
    "int32": np.dtype("<i4"),
    "float32": np.dtype("<f4"),
    "float64": np.dtype("<f8"),
}


def _normalize_dtype(value: str | np.dtype) -> np.dtype:
    if isinstance(value, np.dtype):
        dtype = value
    else:
        dtype = np.dtype(str(value))

    # Normalize endian for multi-byte dtypes. (uint8 is endian-agnostic.)
    if dtype.itemsize > 1:
        dtype = dtype.newbyteorder("<")

    normalized = dtype.name
    if normalized not in _SUPPORTED_DTYPES:
        raise ValueError(
            f"Unsupported dtype {normalized!r}; supported={sorted(_SUPPORTED_DTYPES)}"
        )
    return _SUPPORTED_DTYPES[normalized]


def _validate_shape(shape: Sequence[object]) -> tuple[int, int, int]:
    if len(shape) != 3:
        raise ValueError("shape must be [levels, lat, lon]")
    try:
        levels, lat, lon = (int(shape[0]), int(shape[1]), int(shape[2]))
    except (TypeError, ValueError) as exc:
        raise ValueError("shape must contain integers") from exc

    if levels <= 0 or lat <= 0 or lon <= 0:
        raise ValueError("shape dimensions must be positive")
    return levels, lat, lon


def _json_dumps(payload: Mapping[str, Any]) -> bytes:
    # Canonical-ish encoding to help debugging and deterministic fixtures.
    return (
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        .encode("utf-8")
    )


def encode_volume_pack(
    data: np.ndarray,
    *,
    header: Mapping[str, Any] | None = None,
    compression_level: int = 3,
) -> bytes:
    """Encode a 3D tensor into Volume Pack bytes.

    The header is merged with required fields (required keys win).
    """

    array = np.asarray(data)
    if array.ndim != 3:
        raise ValueError("data must be a 3D array with shape [levels, lat, lon]")

    header_in: dict[str, Any] = dict(header or {})
    dtype = _normalize_dtype(header_in.get("dtype", array.dtype))

    if array.dtype != dtype:
        array = array.astype(dtype, copy=False)
    if not array.flags["C_CONTIGUOUS"]:
        array = np.ascontiguousarray(array)

    required: dict[str, Any] = {
        "version": int(header_in.get("version", 1) or 1),
        "shape": list(map(int, array.shape)),
        "dtype": dtype.name,
        "scale": float(header_in.get("scale", 1.0)),
        "offset": float(header_in.get("offset", 0.0)),
        "compression": "zstd",
    }

    merged = {**header_in, **required}
    header_bytes = _json_dumps(merged)
    if len(header_bytes) > MAX_HEADER_BYTES:
        raise ValueError("header JSON is too large")

    compressor = zstd.ZstdCompressor(level=int(compression_level))
    body = compressor.compress(array.tobytes(order="C"))

    return MAGIC + _HEADER_LEN.pack(len(header_bytes)) + header_bytes + body


def decode_volume_pack(payload: bytes | bytearray | memoryview) -> tuple[dict[str, Any], np.ndarray]:
    """Decode Volume Pack bytes into (header, ndarray).

    Decoding is forward-compatible for header schema versions as long as the
    container layout and compression remain compatible.
    """

    view = memoryview(payload)
    if view.nbytes < 8:
        raise ValueError("payload is too small to be a Volume Pack")

    if view[:4].tobytes() != MAGIC:
        raise ValueError("invalid magic; not a Volume Pack")

    (header_len,) = _HEADER_LEN.unpack(view[4:8])
    if header_len <= 0:
        raise ValueError("invalid header length")
    if header_len > MAX_HEADER_BYTES:
        raise ValueError("header length exceeds maximum")

    header_start = 8
    header_end = header_start + int(header_len)
    if header_end > view.nbytes:
        raise ValueError("payload truncated while reading header")

    header_bytes = view[header_start:header_end].tobytes()
    try:
        header_obj = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid header JSON") from exc
    if not isinstance(header_obj, dict):
        raise ValueError("header JSON must be an object")

    header: dict[str, Any] = dict(header_obj)

    version_raw = header.get("version", 1)
    if version_raw is None:
        version = 1
    else:
        try:
            version = int(version_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("header.version must be an integer") from exc
    if version < 1:
        # Best-effort for earlier/invalid values: treat as v1 semantics.
        version = 1
    header["version"] = version

    compression = str(header.get("compression", "zstd") or "zstd").lower()
    if compression != "zstd":
        raise ValueError(f"unsupported compression {compression!r}")

    shape = _validate_shape(header.get("shape", ()))
    dtype = _normalize_dtype(str(header.get("dtype", "")))

    elements = int(shape[0]) * int(shape[1]) * int(shape[2])
    expected_nbytes = elements * int(dtype.itemsize)
    if expected_nbytes <= 0:
        raise ValueError("invalid decoded byte size")

    body = view[header_end:].tobytes()
    decompressor = zstd.ZstdDecompressor()
    try:
        decoded = decompressor.decompress(body, max_output_size=expected_nbytes)
    except zstd.ZstdError as exc:
        raise ValueError("zstd decompression failed") from exc
    if len(decoded) != expected_nbytes:
        raise ValueError(
            "decoded body size mismatch "
            f"(expected={expected_nbytes}, got={len(decoded)})"
        )

    array = np.frombuffer(decoded, dtype=dtype).reshape(shape)
    return header, array


def write_volume_pack(
    path: str | Path,
    data: np.ndarray,
    *,
    header: Mapping[str, Any] | None = None,
    compression_level: int = 3,
) -> Path:
    target = Path(path)
    payload = encode_volume_pack(data, header=header, compression_level=compression_level)
    target.write_bytes(payload)
    return target


def read_volume_pack(path: str | Path) -> tuple[dict[str, Any], np.ndarray]:
    source = Path(path)
    return decode_volume_pack(source.read_bytes())
