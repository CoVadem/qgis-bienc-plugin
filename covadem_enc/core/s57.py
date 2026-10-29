"""S-57 (ENC) file discovery helpers."""

import os
from dataclasses import dataclass

from osgeo import gdal

DEPARE = "DEPARE"
S57_EXTENSION = ".000"


@dataclass(frozen=True)
class S57Source:
    path: str
    # Path relative to the input folder (used for naming and the `source_file` column)
    relpath: str

    @property
    def name(self):
        return os.path.basename(self.path)

    @property
    def stem(self):
        return os.path.splitext(os.path.basename(self.path))[0]


def find_s57_files(folder, recursive=False):
    """Return S-57 base cells (*.000) in `folder`, sorted by relative path."""
    folder = os.path.abspath(folder)
    result = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            dirs.sort()
            for name in files:
                if name.lower().endswith(S57_EXTENSION):
                    path = os.path.join(root, name)
                    result.append(S57Source(path, os.path.relpath(path, folder)))
    else:
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            if name.lower().endswith(S57_EXTENSION) and os.path.isfile(path):
                result.append(S57Source(path, name))
    result.sort(key=lambda s: s.relpath.lower())
    return result


def open_s57(path):
    """Open an S-57 file read-only with GDAL; returns a gdal.Dataset or None."""
    with gdal.ExceptionMgr(useExceptions=True):
        try:
            return gdal.OpenEx(path, gdal.OF_VECTOR | gdal.OF_READONLY, allowed_drivers=["S57"])
        except RuntimeError:
            return None


def has_layer(path, layer_name=DEPARE):
    ds = open_s57(path)
    return ds is not None and ds.GetLayerByName(layer_name) is not None
