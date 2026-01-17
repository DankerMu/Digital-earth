from __future__ import annotations


class CldasNetcdfError(Exception):
    """Base error for CLDAS NetCDF parsing/writing."""


class CldasNetcdfOpenError(CldasNetcdfError):
    """Raised when a NetCDF file cannot be opened."""


class CldasNetcdfStructureError(CldasNetcdfError):
    """Raised when the NetCDF dataset structure is unexpected."""


class CldasNetcdfVariableMissingError(CldasNetcdfError):
    """Raised when a required source variable is missing from the dataset."""


class CldasNetcdfMissingDataError(CldasNetcdfError):
    """Raised when missing data cannot be repaired to a complete field."""


class CldasNetcdfWriteError(CldasNetcdfError):
    """Raised when internal files/index cannot be written."""
