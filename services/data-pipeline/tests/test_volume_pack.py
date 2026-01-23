from __future__ import annotations

import json

import numpy as np
import pytest


def _roundtrip(*, data: np.ndarray, header: dict) -> tuple[dict, np.ndarray]:
    from volume.pack import decode_volume_pack, encode_volume_pack

    payload = encode_volume_pack(data, header=header, compression_level=1)
    decoded_header, decoded = decode_volume_pack(payload)
    return decoded_header, decoded


def test_roundtrip_float32_header_fields_preserved() -> None:
    data = (np.arange(2 * 3 * 4, dtype=np.float32) / 10.0).reshape((2, 3, 4))
    header = {
        "version": 1,
        "bbox": {
            "west": -180,
            "south": -90,
            "east": 180,
            "north": 90,
            "bottom": 1000,
            "top": 100,
        },
        "levels": [1000, 925],
        "variable": "cloud_density",
        "valid_time": "2026-01-01T00:00:00Z",
        "scale": 1.0,
        "offset": 0.0,
    }

    decoded_header, decoded = _roundtrip(data=data, header=header)
    assert decoded_header["version"] == 1
    assert decoded_header["compression"] == "zstd"
    assert decoded_header["dtype"] == "float32"
    assert decoded_header["shape"] == [2, 3, 4]
    assert decoded_header["bbox"] == header["bbox"]
    assert decoded_header["levels"] == header["levels"]
    assert decoded_header["variable"] == "cloud_density"
    assert decoded_header["valid_time"] == "2026-01-01T00:00:00Z"
    assert decoded_header["scale"] == pytest.approx(1.0)
    assert decoded_header["offset"] == pytest.approx(0.0)

    assert decoded.shape == (2, 3, 4)
    assert decoded.dtype == np.dtype("<f4")
    np.testing.assert_allclose(decoded, data, rtol=0, atol=0)


def test_encode_casts_dtype_when_requested() -> None:
    data = (np.arange(6, dtype=np.float64) / 3.0).reshape((1, 2, 3))
    decoded_header, decoded = _roundtrip(
        data=data,
        header={"dtype": "float32", "scale": 1.0, "offset": 0.0},
    )
    assert decoded_header["dtype"] == "float32"
    assert decoded.dtype == np.dtype("<f4")
    np.testing.assert_allclose(decoded, data.astype(np.float32), rtol=0, atol=0)


def test_encode_rejects_non_3d_tensor() -> None:
    from volume.pack import encode_volume_pack

    with pytest.raises(ValueError, match="3D"):
        encode_volume_pack(np.zeros((2, 2), dtype=np.float32))


def test_encode_rejects_unsupported_dtype() -> None:
    from volume.pack import encode_volume_pack

    data = np.zeros((1, 1, 1), dtype=np.float32)
    with pytest.raises(ValueError, match="Unsupported dtype"):
        encode_volume_pack(data, header={"dtype": "float16"})


def test_encode_normalizes_non_contiguous_arrays() -> None:
    from volume.pack import decode_volume_pack, encode_volume_pack

    base = np.arange(2 * 3 * 4, dtype=np.float32).reshape((2, 3, 4))
    sliced = base[:, :, ::2]
    assert not sliced.flags["C_CONTIGUOUS"]

    header, decoded = decode_volume_pack(encode_volume_pack(sliced))
    assert header["shape"] == [2, 3, 2]
    np.testing.assert_allclose(decoded, sliced, rtol=0, atol=0)


def test_decode_rejects_invalid_magic() -> None:
    from volume.pack import decode_volume_pack

    with pytest.raises(ValueError, match="magic"):
        decode_volume_pack(b"NOPE" + b"\x00" * 8)


def test_decode_rejects_payload_too_small() -> None:
    from volume.pack import decode_volume_pack

    with pytest.raises(ValueError, match="too small"):
        decode_volume_pack(b"")


def test_decode_rejects_invalid_header_length_zero() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    payload = MAGIC + (0).to_bytes(4, "little")
    with pytest.raises(ValueError, match="header length"):
        decode_volume_pack(payload)


def test_decode_rejects_header_length_exceeds_maximum() -> None:
    from volume.pack import MAGIC, MAX_HEADER_BYTES, decode_volume_pack

    payload = MAGIC + (MAX_HEADER_BYTES + 1).to_bytes(4, "little")
    with pytest.raises(ValueError, match="exceeds"):
        decode_volume_pack(payload)


def test_decode_rejects_truncated_header() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    header = json.dumps({"shape": [1, 1, 1], "dtype": "float32"}).encode("utf-8")
    header_len = (len(header) + 10).to_bytes(4, "little")
    payload = MAGIC + header_len + header
    with pytest.raises(ValueError, match="truncated"):
        decode_volume_pack(payload)


def test_decode_rejects_invalid_header_json() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    header = b"{not-json"
    payload = MAGIC + len(header).to_bytes(4, "little") + header + b""
    with pytest.raises(ValueError, match="header JSON"):
        decode_volume_pack(payload)


def test_decode_rejects_non_object_header_json() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    header = b"[]"
    payload = MAGIC + len(header).to_bytes(4, "little") + header
    with pytest.raises(ValueError, match="must be an object"):
        decode_volume_pack(payload)


def test_decode_rejects_invalid_shape_types() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    header = {"shape": ["x", 1, 1], "dtype": "float32", "compression": "zstd"}
    header_bytes = json.dumps(header).encode("utf-8")
    payload = MAGIC + len(header_bytes).to_bytes(4, "little") + header_bytes + b""
    with pytest.raises(ValueError, match="contain integers"):
        decode_volume_pack(payload)


def test_decode_rejects_invalid_shape_length() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    header = {"shape": [1, 1], "dtype": "float32", "compression": "zstd"}
    header_bytes = json.dumps(header).encode("utf-8")
    payload = MAGIC + len(header_bytes).to_bytes(4, "little") + header_bytes + b""
    with pytest.raises(ValueError, match="shape must be"):
        decode_volume_pack(payload)


def test_decode_rejects_invalid_shape_non_positive() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    header = {"shape": [0, 1, 1], "dtype": "float32", "compression": "zstd"}
    header_bytes = json.dumps(header).encode("utf-8")
    payload = MAGIC + len(header_bytes).to_bytes(4, "little") + header_bytes + b""
    with pytest.raises(ValueError, match="positive"):
        decode_volume_pack(payload)


def test_decode_rejects_invalid_version_type() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    header = {
        "version": "nope",
        "shape": [1, 1, 1],
        "dtype": "float32",
        "compression": "zstd",
    }
    header_bytes = json.dumps(header).encode("utf-8")
    payload = MAGIC + len(header_bytes).to_bytes(4, "little") + header_bytes + b""
    with pytest.raises(ValueError, match="header\\.version"):
        decode_volume_pack(payload)


def test_decode_rejects_invalid_zstd_body() -> None:
    from volume.pack import MAGIC, decode_volume_pack

    header = {"shape": [1, 1, 1], "dtype": "float32", "compression": "zstd"}
    header_bytes = json.dumps(header).encode("utf-8")
    payload = (
        MAGIC + len(header_bytes).to_bytes(4, "little") + header_bytes + b"not-zstd"
    )
    with pytest.raises(ValueError, match="decompression"):
        decode_volume_pack(payload)


def test_decode_rejects_unsupported_compression() -> None:
    from volume.pack import MAGIC, decode_volume_pack, encode_volume_pack

    data = np.zeros((1, 1, 1), dtype=np.float32)
    payload = encode_volume_pack(data)

    header_len = int.from_bytes(payload[4:8], "little")
    header = json.loads(payload[8 : 8 + header_len].decode("utf-8"))
    header["compression"] = "lz4"
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    payload = (
        MAGIC
        + len(header_bytes).to_bytes(4, "little")
        + header_bytes
        + payload[8 + header_len :]
    )
    with pytest.raises(ValueError, match="compression"):
        decode_volume_pack(payload)


def test_decode_rejects_body_size_mismatch() -> None:
    from volume.pack import MAGIC, decode_volume_pack, encode_volume_pack

    data = np.zeros((1, 1, 1), dtype=np.float32)
    payload = encode_volume_pack(data, header={"shape": [1, 1, 1], "dtype": "float32"})

    # Patch header to claim a larger shape without changing the body.
    header_len = int.from_bytes(payload[4:8], "little")
    header = json.loads(payload[8 : 8 + header_len].decode("utf-8"))
    header["shape"] = [1, 1, 2]
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    patched = (
        MAGIC
        + len(header_bytes).to_bytes(4, "little")
        + header_bytes
        + payload[8 + header_len :]
    )
    with pytest.raises(ValueError, match="size mismatch"):
        decode_volume_pack(patched)


def test_decode_normalizes_version_lt_1() -> None:
    from volume.pack import MAGIC, decode_volume_pack, encode_volume_pack

    data = np.zeros((1, 1, 1), dtype=np.float32)
    payload = encode_volume_pack(data)

    header_len = int.from_bytes(payload[4:8], "little")
    header = json.loads(payload[8 : 8 + header_len].decode("utf-8"))
    header["version"] = 0
    header_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    payload = (
        MAGIC
        + len(header_bytes).to_bytes(4, "little")
        + header_bytes
        + payload[8 + header_len :]
    )
    header, _ = decode_volume_pack(payload)
    assert header["version"] == 1


def test_write_and_read_volume_pack(tmp_path) -> None:
    from volume.pack import read_volume_pack, write_volume_pack

    path = tmp_path / "x.volp"
    data = (np.arange(6, dtype=np.float32) / 5.0).reshape((1, 2, 3))
    write_volume_pack(
        path, data, header={"variable": "cloud_density"}, compression_level=1
    )

    header, decoded = read_volume_pack(path)
    assert header["variable"] == "cloud_density"
    np.testing.assert_allclose(decoded, data, rtol=0, atol=0)


def test_encode_rejects_oversized_header() -> None:
    from volume.pack import MAX_HEADER_BYTES, encode_volume_pack

    data = np.zeros((1, 1, 1), dtype=np.float32)
    header = {"pad": "x" * (MAX_HEADER_BYTES + 10)}
    with pytest.raises(ValueError, match="too large"):
        encode_volume_pack(data, header=header)
