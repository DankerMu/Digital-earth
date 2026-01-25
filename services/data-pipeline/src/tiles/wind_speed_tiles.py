from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

import numpy as np
import xarray as xr

from datacube.core import DataCube
from tiling.temperature_tiles import (
    TemperatureTileGenerationResult,
    TemperatureTileGenerator,
    TemperatureTilingError,
)


DEFAULT_WIND_SPEED_LAYER: Final[str] = "ecmwf/wind_speed"
DEFAULT_WIND_SPEED_VARIABLE: Final[str] = "wind_speed"
DEFAULT_WIND_SPEED_LEGEND_FILENAME: Final[str] = "wind_speed_legend.json"

# Keep wind speed tiles subtle so wind vectors remain readable.
DEFAULT_WIND_SPEED_OPACITY: Final[float] = 0.35


def _validate_opacity(value: float) -> float:
    opacity = float(value)
    if not np.isfinite(opacity) or opacity < 0.0 or opacity > 1.0:
        raise ValueError("opacity must be between 0 and 1")
    return opacity


@dataclass(frozen=True)
class WindSpeedTileGenerationResult:
    layer: str
    variable: str
    time: str
    level: str
    opacity: float
    output_dir: Path
    min_zoom: int
    max_zoom: int
    formats: tuple[str, ...]
    tiles_written: int


class WindSpeedTileGenerator(TemperatureTileGenerator):
    """Generate semi-transparent wind speed raster tiles."""

    def __init__(
        self,
        cube: DataCube,
        *,
        opacity: float = DEFAULT_WIND_SPEED_OPACITY,
        variable: str = DEFAULT_WIND_SPEED_VARIABLE,
        layer: str = DEFAULT_WIND_SPEED_LAYER,
        legend_filename: str = DEFAULT_WIND_SPEED_LEGEND_FILENAME,
    ) -> None:
        super().__init__(
            cube,
            variable=variable,
            layer=layer,
            legend_filename=legend_filename,
        )
        self._opacity = _validate_opacity(opacity)

    @classmethod
    def from_dataset(
        cls,
        ds: xr.Dataset,
        *,
        opacity: float = DEFAULT_WIND_SPEED_OPACITY,
        variable: str = DEFAULT_WIND_SPEED_VARIABLE,
        layer: str = DEFAULT_WIND_SPEED_LAYER,
        legend_filename: str = DEFAULT_WIND_SPEED_LEGEND_FILENAME,
    ) -> "WindSpeedTileGenerator":
        return cls(
            DataCube.from_dataset(ds),
            opacity=opacity,
            variable=variable,
            layer=layer,
            legend_filename=legend_filename,
        )

    @property
    def opacity(self) -> float:
        return self._opacity

    def _resolve_variable_name(self, ds: xr.Dataset) -> str:
        preferred = (self.variable or "").strip()
        present = {name.lower(): name for name in ds.data_vars}
        direct = present.get(preferred.lower())
        if direct is not None:
            return direct

        available = ", ".join(sorted(ds.data_vars))
        raise TemperatureTilingError(
            f"Wind speed variable {preferred!r} not found; available=[{available}]"
        )

    def _colorize(self, values: np.ndarray) -> np.ndarray:
        rgba = super()._colorize(values)
        opacity = self._opacity
        if opacity >= 1.0:
            return rgba

        out = rgba.copy()
        alpha = out[..., 3].astype(np.float32, copy=False)
        scaled = np.rint(alpha * np.float32(opacity))
        out[..., 3] = np.clip(scaled, 0, 255).astype(np.uint8)
        return out

    def generate(
        self,
        output_dir: str | Path,
        *,
        valid_time: object,
        level: object,
        min_zoom: int | None = None,
        max_zoom: int | None = None,
        tile_size: int | None = None,
        formats: Sequence[str] = ("png", "webp"),
    ) -> WindSpeedTileGenerationResult:
        result: TemperatureTileGenerationResult = super().generate(
            output_dir,
            valid_time=valid_time,
            level=level,
            min_zoom=min_zoom,
            max_zoom=max_zoom,
            tile_size=tile_size,
            formats=formats,
        )
        return WindSpeedTileGenerationResult(
            layer=result.layer,
            variable=result.variable,
            time=result.time,
            level=result.level,
            opacity=self._opacity,
            output_dir=result.output_dir,
            min_zoom=result.min_zoom,
            max_zoom=result.max_zoom,
            formats=result.formats,
            tiles_written=result.tiles_written,
        )
