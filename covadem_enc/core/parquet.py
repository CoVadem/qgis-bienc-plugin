"""Convert S-57 layers (DEPARE) to GeoParquet, either merged into one file or one file per source.

Uses the OGR API directly (instead of an OGR VRT union) so that the merged schema keeps the
original field types, and so progress/cancellation can be reported per feature batch.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from enum import IntEnum

from osgeo import gdal, ogr, osr

from .s57 import DEPARE, open_s57

FORMAT_VERSION = 1
SOURCE_FIELD = "source_file"
VSIMEM_ROOT = "/vsimem/covadem_enc"
LAYER_CREATION_OPTIONS = ["COMPRESSION=ZSTD", "SORT_BY_BBOX=YES", "WRITE_COVERING_BBOX=YES"]
_POLYGONAL = {ogr.wkbPolygon, ogr.wkbMultiPolygon, ogr.wkbCurvePolygon, ogr.wkbMultiSurface}


class Layout(IntEnum):
    MERGED = 0
    PER_FILE = 1


class Location(IntEnum):
    MEMORY = 0
    SOURCE = 1
    TEMP = 2
    CUSTOM = 3


LAYOUT_LABELS = ["One merged GeoParquet file", "One GeoParquet file per source file"]
LOCATION_LABELS = [
    "In memory (current QGIS session only)",
    "Next to the source files",
    "System temp folder (cached between sessions)",
    "Custom folder",
]


class ConversionCanceled(Exception):
    pass


@dataclass
class ConversionResult:
    files: list = field(default_factory=list)
    converted: int = 0
    reused: int = 0
    features: int = 0
    no_layer: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    skipped_geometries: int = 0
    warnings: int = 0


class _NullFeedback:
    def isCanceled(self):  # pylint: disable=invalid-name
        return False

    def setProgress(self, _value):  # pylint: disable=invalid-name
        pass

    def pushInfo(self, msg):  # pylint: disable=invalid-name
        print(msg)

    def pushWarning(self, msg):  # pylint: disable=invalid-name
        print(msg)


def parquet_driver_available():
    return ogr.GetDriverByName("Parquet") is not None


def _join(folder, *parts):
    if folder.startswith("/vsimem/"):
        return "/".join([folder.rstrip("/"), *[p.replace("\\", "/") for p in parts]])
    return os.path.join(folder, *parts)


def _folder_key(input_folder, recursive):
    key = f"{os.path.normcase(os.path.abspath(input_folder))}|{int(bool(recursive))}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _folder_label(input_folder):
    return os.path.basename(os.path.normpath(input_folder)) or "enc"


def resolve_output_folder(location, input_folder, recursive=False, custom_folder=None):
    label = f"{_folder_label(input_folder)}_{_folder_key(input_folder, recursive)}"
    location = Location(location)
    if location == Location.MEMORY:
        return f"{VSIMEM_ROOT}/{label}"
    if location == Location.SOURCE:
        return os.path.abspath(input_folder)
    if location == Location.TEMP:
        return os.path.join(tempfile.gettempdir(), "covadem_enc", label)
    if not custom_folder:
        raise ValueError("A custom output folder is required")
    return os.path.abspath(custom_folder)


def merged_output_path(output_folder, input_folder, layer_name=DEPARE):
    return _join(output_folder, f"{_folder_label(input_folder)}_{layer_name}.parquet")


def per_file_output_path(output_folder, source, layer_name=DEPARE):
    return _join(output_folder, f"{os.path.splitext(source.relpath)[0]}_{layer_name}.parquet")


def _mkdirs(folder):
    if not folder.startswith("/vsimem/"):
        os.makedirs(folder, exist_ok=True)


def _mtime(path):
    stat = gdal.VSIStatL(path)
    return None if stat is None else stat.mtime


def _exists(path):
    return gdal.VSIStatL(path) is not None


def _remove(path):
    if _exists(path):
        gdal.Unlink(path)


def _replace(tmp_path, final_path):
    _remove(final_path)
    gdal.Rename(tmp_path, final_path)


def _read_text(path):
    fp = gdal.VSIFOpenL(path, "rb")
    if fp is None:
        return None
    try:
        size = gdal.VSIStatL(path).size
        return gdal.VSIFReadL(1, size, fp).decode("utf-8")
    finally:
        gdal.VSIFCloseL(fp)


def _write_text(path, text):
    data = text.encode("utf-8")
    fp = gdal.VSIFOpenL(path, "wb")
    try:
        gdal.VSIFWriteL(data, 1, len(data), fp)
    finally:
        gdal.VSIFCloseL(fp)


def _manifest(sources, layer_name):
    entries = []
    for src in sources:
        st = os.stat(src.path)
        entries.append([src.relpath.replace("\\", "/"), st.st_size, int(st.st_mtime)])
    return {"format_version": FORMAT_VERSION, "layer": layer_name, "sources": entries}


def _manifest_path(parquet_path):
    return parquet_path[: -len(".parquet")] + ".manifest.json"


def _merged_is_fresh(path, sources, layer_name):
    if not _exists(path):
        return False
    text = _read_text(_manifest_path(path))
    if not text:
        return False
    try:
        return json.loads(text) == _manifest(sources, layer_name)
    except ValueError:
        return False


def _per_file_is_fresh(path, source):
    out_mtime = _mtime(path)
    return out_mtime is not None and out_mtime >= int(os.path.getmtime(source.path))


def _merge_field_type(a, b):
    if a == b:
        return a
    numeric = {ogr.OFTInteger, ogr.OFTInteger64, ogr.OFTReal}
    if a in numeric and b in numeric:
        return ogr.OFTReal if ogr.OFTReal in (a, b) else ogr.OFTInteger64
    return ogr.OFTString


def _merge_schema(fields, defn):
    """Merge the field definitions of `defn` into the ordered dict `fields` (name -> ogr.FieldDefn)."""
    for i in range(defn.GetFieldCount()):
        fd = defn.GetFieldDefn(i)
        name = fd.GetName()
        if name not in fields:
            fields[name] = ogr.FieldDefn(name, fd.GetType())
            fields[name].SetSubType(fd.GetSubType())
            fields[name].SetWidth(fd.GetWidth())
            fields[name].SetPrecision(fd.GetPrecision())
        elif fields[name].GetType() != fd.GetType():
            fields[name] = ogr.FieldDefn(name, _merge_field_type(fields[name].GetType(), fd.GetType()))


def _default_srs():
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    return srs


def _as_multipolygon(geom):
    if geom is None:
        return None
    gtype = ogr.GT_Flatten(geom.GetGeometryType())
    if gtype not in _POLYGONAL:
        return None
    geom = geom.GetLinearGeometry() if gtype in (ogr.wkbCurvePolygon, ogr.wkbMultiSurface) else geom.Clone()
    return ogr.ForceToMultiPolygon(geom)


@dataclass
class _Schema:
    sources: list
    fields: list
    srs: object


def _scan(sources, layer_name, result, feedback, progress_start, progress_span):
    """Find sources containing `layer_name` and build the merged schema.

    Datasets are closed again so that large folders don't keep every S-57 file in memory.
    """
    matching, fields, srs = [], {}, None
    count = max(len(sources), 1)
    for i, source in enumerate(sources):
        if feedback.isCanceled():
            raise ConversionCanceled()
        ds = open_s57(source.path)
        if ds is None:
            result.failed.append(source.relpath)
            feedback.pushWarning(f"Could not open {source.relpath}")
        else:
            layer = ds.GetLayerByName(layer_name)
            if layer is None:
                result.no_layer.append(source.relpath)
            else:
                matching.append(source)
                _merge_schema(fields, layer.GetLayerDefn())
                if srs is None and layer.GetSpatialRef() is not None:
                    srs = layer.GetSpatialRef().Clone()
            layer = None
        ds = None
        feedback.setProgress(progress_start + progress_span * (i + 1) / count)
    return _Schema(matching, list(fields.values()), srs or _default_srs())


def _write_parquet(dst_path, schema, layer_name, result, feedback, progress_start, progress_span):
    """Write the `layer_name` layer of all `schema.sources` into one GeoParquet file (atomically)."""
    tmp_path = f"{dst_path}.tmp{os.getpid()}.parquet"
    _remove(tmp_path)
    driver = ogr.GetDriverByName("Parquet")
    out_ds = driver.CreateDataSource(tmp_path)
    try:
        out_layer = out_ds.CreateLayer(
            os.path.splitext(os.path.basename(dst_path))[0], schema.srs, ogr.wkbMultiPolygon, options=LAYER_CREATION_OPTIONS
        )
        out_layer.CreateField(ogr.FieldDefn(SOURCE_FIELD, ogr.OFTString))
        for fd in schema.fields:
            out_layer.CreateField(fd)
        out_defn = out_layer.GetLayerDefn()
        src_index = out_defn.GetFieldIndex(SOURCE_FIELD)

        count = max(len(schema.sources), 1)
        written = 0
        for i, source in enumerate(schema.sources):
            ds = open_s57(source.path)
            layer = None if ds is None else ds.GetLayerByName(layer_name)
            if layer is None:
                raise RuntimeError(f"Could not read {layer_name} from {source.relpath}")
            in_defn = layer.GetLayerDefn()
            index_map = [out_defn.GetFieldIndex(in_defn.GetFieldDefn(j).GetName()) for j in range(in_defn.GetFieldCount())]
            relpath = source.relpath.replace("\\", "/")
            for feature in layer:
                geom = _as_multipolygon(feature.GetGeometryRef())
                if geom is None:
                    result.skipped_geometries += 1
                    continue
                out_feature = ogr.Feature(out_defn)
                out_feature.SetFromWithMap(feature, True, index_map)
                out_feature.SetField(src_index, relpath)
                out_feature.SetGeometryDirectly(geom)
                out_layer.CreateFeature(out_feature)
                written += 1
                if written % 2000 == 0 and feedback.isCanceled():
                    raise ConversionCanceled()
            layer = None
            ds = None
            feedback.setProgress(progress_start + progress_span * (i + 1) / count)
        out_layer = None
        out_ds.Close()
        out_ds = None
        _replace(tmp_path, dst_path)
        result.features += written
    except BaseException:
        out_ds = None
        _remove(tmp_path)
        raise


def convert_sources(
    sources,
    input_folder,
    output_folder,
    layout=Layout.MERGED,
    reuse_existing=True,
    layer_name=DEPARE,
    feedback=None,
):
    """Convert `sources` (list of S57Source) to GeoParquet in `output_folder`.

    Returns a ConversionResult; raises ConversionCanceled when the feedback is canceled.
    """
    feedback = feedback or _NullFeedback()
    result = ConversionResult()
    if not parquet_driver_available():
        raise RuntimeError("The GDAL Parquet driver is not available in this QGIS installation")

    warnings = []

    def error_handler(err_class, _err_no, msg):
        if err_class == gdal.CE_Warning:
            warnings.append(msg)
        elif err_class >= gdal.CE_Failure:
            feedback.pushWarning(f"GDAL: {msg}")

    with gdal.ExceptionMgr(useExceptions=True), ogr.ExceptionMgr(useExceptions=True), osr.ExceptionMgr(useExceptions=True):
        gdal.PushErrorHandler(error_handler)
        try:
            _mkdirs(output_folder)
            if Layout(layout) == Layout.MERGED:
                _convert_merged(sources, input_folder, output_folder, reuse_existing, layer_name, result, feedback)
            else:
                _convert_per_file(sources, output_folder, reuse_existing, layer_name, result, feedback)
        finally:
            gdal.PopErrorHandler()
    result.warnings = len(warnings)
    feedback.setProgress(100)
    return result


def _convert_merged(sources, input_folder, output_folder, reuse_existing, layer_name, result, feedback):
    dst_path = merged_output_path(output_folder, input_folder, layer_name)
    if reuse_existing and _merged_is_fresh(dst_path, sources, layer_name):
        feedback.pushInfo(f"Reusing up-to-date GeoParquet file {dst_path}")
        result.files.append(dst_path)
        result.reused = 1
        return

    feedback.pushInfo(f"Reading {len(sources)} S-57 file(s)…")
    schema = _scan(sources, layer_name, result, feedback, 0, 10)
    if not schema.sources:
        return
    feedback.pushInfo(f"Writing {dst_path}…")
    try:
        _write_parquet(dst_path, schema, layer_name, result, feedback, 10, 90)
    except RuntimeError as err:
        raise RuntimeError(f"Failed to write {dst_path}: {err}") from err
    _write_text(_manifest_path(dst_path), json.dumps(_manifest(sources, layer_name)))
    result.files.append(dst_path)
    result.converted = 1


def _convert_per_file(sources, output_folder, reuse_existing, layer_name, result, feedback):
    count = max(len(sources), 1)
    for i, source in enumerate(sources):
        if feedback.isCanceled():
            raise ConversionCanceled()
        dst_path = per_file_output_path(output_folder, source, layer_name)
        if reuse_existing and _per_file_is_fresh(dst_path, source):
            result.files.append(dst_path)
            result.reused += 1
        else:
            schema = _scan([source], layer_name, result, feedback, 100 * i / count, 0)
            if schema.sources:
                try:
                    _mkdirs(os.path.dirname(dst_path))
                    _write_parquet(dst_path, schema, layer_name, result, feedback, 100 * i / count, 100 / count)
                    result.files.append(dst_path)
                    result.converted += 1
                except RuntimeError as err:
                    result.failed.append(source.relpath)
                    feedback.pushWarning(f"Failed to convert {source.relpath}: {err}")
        feedback.setProgress(100 * (i + 1) / count)
