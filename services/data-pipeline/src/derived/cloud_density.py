from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

import numpy as np
import xarray as xr


class CloudDensityDerivationError(RuntimeError):
    pass


RH_VAR_CANDIDATES: Final[tuple[str, ...]] = (
    "rh",
    "r",
    "relative_humidity",
    "relativeHumidity",
    "RELATIVE_HUMIDITY",
    "RH",
)


def _normalize_units_text(value: object) -> str:
    return str(value or "").strip()


def _resolve_rh_fraction_scale(*, units: str, da: xr.DataArray) -> float:
    """Return the multiplicative factor to convert RH into [0, 1]."""

    normalized_units = _normalize_units_text(units).lower()
    if normalized_units:
        if "%" in normalized_units or "percent" in normalized_units:
            return 0.01
        if normalized_units in {"1"} or "fraction" in normalized_units:
            return 1.0

    vmax = float(da.max(skipna=True).item())
    if not np.isfinite(vmax):
        return 1.0

    if vmax > 1.5:
        return 0.01
    return 1.0


def normalize_relative_humidity(da: xr.DataArray) -> xr.DataArray:
    """Normalize RH into a float32 fraction in [0, 1] when possible."""

    scale = _resolve_rh_fraction_scale(
        units=_normalize_units_text(da.attrs.get("units")), da=da
    )
    out = da.astype(np.float32) * np.float32(scale)
    out = out.astype(np.float32)
    out.name = da.name
    out.attrs = dict(da.attrs)
    out.attrs["units"] = "1"
    out.attrs.setdefault("standard_name", "relative_humidity")
    return out


def smoothstep(edge0: float, edge1: float, x: xr.DataArray) -> xr.DataArray:
    denom = float(edge1) - float(edge0)
    if denom == 0.0:
        raise CloudDensityDerivationError("smoothstep requires edge1 != edge0")
    t = ((x - float(edge0)) / denom).clip(min=0.0, max=1.0)
    return t * t * (3.0 - 2.0 * t)


@dataclass(frozen=True)
class CloudDensityThresholds:
    rh0: float
    rh1: float

    @classmethod
    def resolve(
        cls,
        *,
        rh0: float | None = None,
        rh1: float | None = None,
    ) -> "CloudDensityThresholds":
        if rh0 is None or rh1 is None:
            from config import get_settings

            settings = get_settings()
            if rh0 is None:
                rh0 = float(settings.pipeline.cloud_density_rh0)
            if rh1 is None:
                rh1 = float(settings.pipeline.cloud_density_rh1)

        rh0_f = float(rh0)
        rh1_f = float(rh1)

        if (rh0_f > 1.0) != (rh1_f > 1.0):
            raise CloudDensityDerivationError(
                "RH0/RH1 must use consistent units (both fraction ≤ 1 or both percent > 1)"
            )

        if rh0_f > 1.0:
            rh0_f /= 100.0
            rh1_f /= 100.0

        if not (0.0 <= rh0_f < rh1_f <= 1.0):
            raise CloudDensityDerivationError(
                f"Invalid RH thresholds after normalization: rh0={rh0_f}, rh1={rh1_f}"
            )

        return cls(rh0=rh0_f, rh1=rh1_f)


def derive_cloud_density_from_rh(
    rh: xr.DataArray,
    *,
    thresholds: CloudDensityThresholds | None = None,
) -> xr.DataArray:
    """Derive cloud density from RH via smoothstep.

    The returned density is float32, named `cloud_density`, and clamped to [0, 1]
    for all finite values.
    """

    resolved = thresholds or CloudDensityThresholds.resolve()
    rh_frac = normalize_relative_humidity(rh)
    density = smoothstep(resolved.rh0, resolved.rh1, rh_frac)
    density = density.clip(min=0.0, max=1.0).astype(np.float32, copy=False)
    density.name = "cloud_density"
    density.attrs = {
        "units": "1",
        "long_name": "Cloud density derived from relative humidity",
        "rh0": float(resolved.rh0),
        "rh1": float(resolved.rh1),
        "mapping": "smoothstep(rh0, rh1, rh)",
    }
    return density


def _descriptor_text(name: str, da: xr.DataArray) -> str:
    parts: Iterable[object] = (
        name,
        da.name,
        da.attrs.get("standard_name"),
        da.attrs.get("long_name"),
    )
    return " ".join(str(part or "") for part in parts).lower()


def resolve_rh_variable_name(ds: xr.Dataset, *, preferred: str | None = None) -> str:
    if preferred is not None:
        key = str(preferred).strip()
        if key == "":
            raise CloudDensityDerivationError("RH variable name must not be empty")
        if key not in ds.data_vars:
            raise CloudDensityDerivationError(
                f"RH variable {key!r} not found; available={list(ds.data_vars)}"
            )
        return key

    present = {name.lower(): name for name in ds.data_vars}
    for candidate in RH_VAR_CANDIDATES:
        found = present.get(candidate.lower())
        if found is not None:
            return found

    for name in ds.data_vars:
        if "relative_humidity" in _descriptor_text(name, ds[name]):
            return name
        if "relative humidity" in _descriptor_text(name, ds[name]):
            return name

    raise CloudDensityDerivationError(
        f"Unable to infer RH variable; tried={list(RH_VAR_CANDIDATES)} available={list(ds.data_vars)}"
    )


def derive_cloud_density_dataset(
    ds: xr.Dataset,
    *,
    rh_variable: str | None = None,
    thresholds: CloudDensityThresholds | None = None,
) -> xr.Dataset:
    name = resolve_rh_variable_name(ds, preferred=rh_variable)
    density = derive_cloud_density_from_rh(ds[name], thresholds=thresholds)
    return xr.Dataset({"cloud_density": density})
