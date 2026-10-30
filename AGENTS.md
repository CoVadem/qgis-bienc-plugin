# Plan: QGIS 4 "CoVadem ENC" Processing plugin (from AddEncMaps.py)

## Problem
Pick folder → for every `*.000` (S-57 ENC) load the `DEPARE`
layer, apply a graduated "Blues" renderer on `DRVAL1` (0–7 m, 14 classes + invalid <0 purple + >7),
add to a layer-tree group. Needs to become a proper QGIS 4.0+ (Qt6) plugin exposed in the
Processing Toolbox, plus an option to convert `.000` → GeoParquet first (GDAL S-57 access is slow,
mostly because S-57 has no spatial index and every pan/zoom re-reads 200+ files).

## Decisions (confirmed / assumed)
- Target **QGIS 4.0+ only** (`qgisMinimumVersion=4.0`, `supportsQt6=True`, fully-scoped enums,
  `qgis.PyQt` imports). Test with local QGIS 4.2.2 (GDAL 3.13.3, Parquet + S57 drivers present, Python 3.12).
- Separate provider: id `covadem_enc`, name **"CoVadem ENC"** (distinct from qgis-cvd-plugin's "CoVadem").
- Layer: **DEPARE only**, styled exactly as today (renderer logic preserved).
- UI (assumed, user unavailable): standard Processing dialog with well-organised params,
  advanced params flagged `FlagAdvanced`; validation in `checkParameterValues` for invalid combos.
- Test data: `tests\example`
  (208 flat `.000` files, ~132 MB, max 3.2 MB). DEPARE has `Geometry: Unknown`, EPSG:4326,
  fields incl. `DRVAL1/DRVAL2`, StringList/IntegerList columns.
- Note: standalone `ogrinfo` needs `GDAL_DATA=...\apps\gdal\share\gdal` for S-57 object classes
  (inside QGIS it's set already); plugin uses in-process GDAL so it's fine.

## Package layout (repo root = plugin `covadem_enc/`)
```
covadem_enc/
  __init__.py            classFactory
  plugin.py              CovademEncPlugin: initProcessing/initGui/unload (provider register)
  provider.py            CovademEncProvider (id covadem_enc, name "CoVadem ENC", icon)
  algorithms/
    load_enc_depare.py   "Load ENC depth areas (DEPARE)"
    convert_enc_parquet.py "Convert ENC to GeoParquet"
  core/
    s57.py               find .000 files, DEPARE detection, GDAL S57 open options
    parquet.py           conversion (single merged / per-file), cache freshness, /vsimem
    styling.py           apply_depare_renderer (ported from AddEncMaps)
  icon.png (simple svg/png)
  metadata.txt
  LICENSE, README.md
scripts/ build zip (git archive like cvd plugin, prefix covadem_enc/)
```
`AddEncMaps.py` stays as reference (or moved to `legacy/`).

## Algorithm 1: Load ENC depth areas (DEPARE)  — group "ENC"
Parameters:
- `INPUT_FOLDER` (folder), `RECURSIVE` (bool, default False)
- `SOURCE_MODE` enum: **Read S-57 directly** | **Convert to GeoParquet, then load** (default)
- `PARQUET_LAYOUT` enum: One merged file | One file per source
- `PARQUET_LOCATION` enum: In memory (/vsimem, session only) | Next to source files | Temp dir | Custom folder
- `PARQUET_FOLDER` (folder, optional; required when Custom)
- `REUSE_EXISTING` (bool, default True; skip conversion if parquet newer than sources) [advanced]
- `GROUP_NAME` (string, default = folder name) [advanced]
- `APPLY_STYLE` (bool, default True), `MIN_DEPTH`/`MAX_DEPTH`/`CLASSES` (0/7/14) [advanced]
Behaviour:
- Discover files; per file check DEPARE exists via `gdal.OpenEx(..., OF_VECTOR|OF_READONLY)` (single open,
  not QGIS open + reopen like the script).
- Direct mode: one layer per file `path|layername=DEPARE`.
- Parquet mode: call shared conversion (core/parquet.py), then layers from parquet(s);
  merged file = one layer with `source_file` column.
- Conversion via `gdal.VectorTranslate` (in-process): layer DEPARE, `-nlt PROMOTE_TO_MULTI` filtered
  to polygons (`PRIM=3` / area geometries) to avoid Unknown-geometry splitting, add `source_file`
  field, `-lco COMPRESSION=ZSTD`, `-lco ROW_GROUP_SIZE`, `-lco SORT_BY_BBOX=YES` (spatial-ish index,
  GDAL ≥3.9), `WRITE_COVERING_BBOX=YES`. Per-file conversions parallelised with a ThreadPool
  (GDAL releases GIL); merged = append sequentially or merge per-file vsimem outputs.
  List-typed columns kept (Parquet supports them); fall back to string if driver complains.
- Cancellation + progress via feedback per file; failures logged and skipped (like the script).
- Layer adding runs on main thread: build layers in `processAlgorithm`, then in
  `postProcessAlgorithm` add to project under a group inserted at top (as the script), apply renderer.
  Outputs: `OUTPUT_LAYERS` (multiple layers), `PARQUET_FILES` (list), counts.
- In-memory mode: warn that data disappears on project reload.

## Algorithm 2: Convert ENC to GeoParquet  — group "ENC"
Same conversion params without loading (`INPUT_FOLDER`, `RECURSIVE`, `PARQUET_LAYOUT`,
output folder destination / file destination, `OVERWRITE`). Lets users pre-convert once, batchable.

## Styling (core/styling.py)
Port `apply_default_blue_gradient` / `create_symbol` with QGIS 4 APIs:
`QgsGraduatedSymbolRenderer.Mode`→ `Qgis.GraduatedMethod`/`setClassificationMethod` as appropriate,
`layer.geometryType()` returns `Qgis.GeometryType`, Blues ramp from `QgsStyle.defaultStyle()`,
same colors/stroke (QColor(16,16,32), 0.06), invalid range -10..0 purple, top range max..max*10.

## Validation / testing
- Run with QGIS 4.2.2 `python-qgis.bat` headless (`QgsApplication` + `processing.core.Processing`):
  register provider, run both algorithms on test folder for all 4 locations × 2 layouts + direct mode,
  assert layer validity, feature counts equal between direct and parquet, renderer set.
- Benchmark: direct vs parquet load + full feature iteration / extent render, report numbers.
- Manually-checkable: plugin zip installs in QGIS 4.2.2, toolbox shows "CoVadem ENC".
- Clean temporary outputs afterwards.

## Notes / risks
- Parquet conversion still reads S-57 once; gains come on subsequent use & rendering (reuse cache).
- `/vsimem` parquet works with QGIS OGR provider within session only; not saved with project.
- If GDAL lacks Parquet driver (unlikely on 4.x Windows builds), algorithm raises clear
  `QgsProcessingException` and suggests direct mode.
