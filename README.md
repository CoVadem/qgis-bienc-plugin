# CoVadem ENC – QGIS plugin

QGIS 4.0+ plugin that loads S-57 (ENC) depth areas (`DEPARE`) from a folder of `.000` files,
styled with a blue depth gradient on `DRVAL1` (negative values purple). It is the plugin version of
the original `AddEncMaps.py` console script.

The algorithms are available in **Processing Toolbox → CoVadem ENC → ENC (S-57)**:

| Algorithm | Description |
|---|---|
| **Load ENC depth areas (DEPARE)** | Loads DEPARE from all `.000` files into a new layer group, either directly from S-57 or via GeoParquet (default). |
| **Convert ENC to GeoParquet** | Only converts DEPARE to GeoParquet (merged or per file) into an output folder. |

## Requirements

QGIS 4.0+ is required. The plugin uses the GDAL S-57 driver; GeoParquet conversion also requires the
GDAL Parquet driver. Both are provided by the QGIS/GDAL installation when enabled. No additional
Python packages are required.

## GeoParquet mode

Reading many S-57 files through GDAL is slow to render: S-57 has no spatial index, so every pan or zoom
re-reads every file. The plugin can first convert DEPARE to GeoParquet. The output is spatially sorted,
ZSTD-compressed and has a bbox covering column, so later reads and rendering are fast.

* **Layout**: one merged file with a `source_file` column (fastest to render), or one file per source
  (`<cell>_DEPARE.parquet`).
* **Location**:
  * in memory (`/vsimem`, current session only, not restorable from a saved project)
  * next to the source files
  * system temp folder (`%TEMP%\covadem_enc\…`, kept between sessions)
  * a custom folder
* **Reuse**: up-to-date files are reused. Merged files are checked against a `.manifest.json` listing
  the sources' sizes and modification times. Per-file outputs are checked against the source file's
  modification time.

Benchmark (208 cells, 108,754 DEPARE polygons, QGIS 4.2.2, 1600×1000 render):

| Source | Load | Render full extent | Render zoomed |
|---|---|---|---|
| S-57 direct (198 layers) | ~9 s | ~12–20 s | ~8 s |
| GeoParquet, merged (1 layer) | ~25–35 s first time, instant when reused | ~5 s | ~0.2 s |
| GeoParquet, per file | ~25–45 s first time, ~1 s when reused | ~7–9 s | ~3 s |

## Install

```powershell
.\build.ps1            # creates build\covadem_enc.zip
```

Then use QGIS → *Plugins → Manage and Install Plugins → Install from ZIP*.
For development, link or copy the `covadem_enc` folder into your QGIS profile's `python\plugins` folder.

## License

This plugin is licensed under GPL-2.0-or-later. See [LICENSE](LICENSE).

## Tests

```powershell
& "C:\Program Files\QGIS 4.2.2\bin\python-qgis.bat" tests\test_algorithms.py <folder-with-000-files>
```
