from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import xarray as xr

from datacube.errors import DataCubeValidationError
from datacube.normalize import normalize_datacube_dataset
from datacube.storage import DataCubeWriteOptions, open_datacube, write_datacube
from datacube.types import DataCubeFormat


@dataclass(frozen=True)
class DataCube:
    """Internal unified structure for gridded weather data.

    Canonical dataset requirements:
    - dims include: time, lat, lon; level is always present (surface => length 1)
    - data variables are float32 and use NaN for missing values
    - coordinates are 1D: lat, lon, level
    """

    dataset: xr.Dataset

    @classmethod
    def from_dataset(cls, ds: xr.Dataset) -> "DataCube":
        return cls(dataset=normalize_datacube_dataset(ds))

    @classmethod
    def open(
        cls,
        path: Union[str, Path],
        *,
        format: Optional[DataCubeFormat] = None,
        engine: Optional[str] = None,
    ) -> "DataCube":
        with open_datacube(path, format=format, engine=engine) as ds:
            ds.load()
        return cls.from_dataset(ds)

    def validate(self) -> None:
        ds = self.dataset
        required = {"time", "lat", "lon", "level"}
        missing = [dim for dim in sorted(required) if dim not in ds.dims]
        if missing:
            raise DataCubeValidationError(
                f"DataCube missing required dimensions: {missing}; dims={list(ds.dims)}"
            )

    def write(
        self,
        path: Union[str, Path],
        *,
        format: Optional[DataCubeFormat] = None,
        engine: Optional[str] = None,
        options: Optional[DataCubeWriteOptions] = None,
    ) -> Path:
        self.validate()
        return write_datacube(
            self.dataset,
            path,
            format=format,
            engine=engine,
            options=options,
        )
