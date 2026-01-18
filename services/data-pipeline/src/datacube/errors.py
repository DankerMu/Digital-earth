from __future__ import annotations


class DataCubeError(RuntimeError):
    pass


class DataCubeDecodeError(DataCubeError):
    pass


class DataCubeValidationError(DataCubeError):
    pass


class DataCubeStorageError(DataCubeError):
    pass

