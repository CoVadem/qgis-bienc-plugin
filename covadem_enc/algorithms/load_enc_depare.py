import os

from qgis.core import (
    Qgis,
    QgsProcessingException,
    QgsProcessingOutputMultipleLayers,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProject,
    QgsVectorLayer,
)

from ..core.parquet import (
    LAYOUT_LABELS,
    LOCATION_LABELS,
    ConversionCanceled,
    Layout,
    Location,
    convert_sources,
    parquet_driver_available,
    per_file_output_path,
    resolve_output_folder,
)
from ..core.s57 import DEPARE, find_s57_files, has_layer
from ..core.styling import apply_depth_renderer
from .base import CovademEncAlgorithm
from .convert_enc_parquet import report_result

MODE_DIRECT = 0
MODE_PARQUET = 1


class LoadEncDepareAlgorithm(CovademEncAlgorithm):
    INPUT_FOLDER = "INPUT_FOLDER"
    RECURSIVE = "RECURSIVE"
    SOURCE_MODE = "SOURCE_MODE"
    PARQUET_LAYOUT = "PARQUET_LAYOUT"
    PARQUET_LOCATION = "PARQUET_LOCATION"
    PARQUET_FOLDER = "PARQUET_FOLDER"
    REUSE_EXISTING = "REUSE_EXISTING"
    GROUP_NAME = "GROUP_NAME"
    APPLY_STYLE = "APPLY_STYLE"
    MIN_DEPTH = "MIN_DEPTH"
    MAX_DEPTH = "MAX_DEPTH"
    CLASSES = "CLASSES"
    OUTPUT_LAYERS = "OUTPUT_LAYERS"
    PARQUET_FILES = "PARQUET_FILES"
    LAYER_COUNT = "LAYER_COUNT"

    def __init__(self):
        super().__init__()
        self._to_load = []
        self._group_name = ""
        self._style = None

    def name(self):
        return "load_enc_depare"

    def displayName(self):  # pylint: disable=invalid-name
        return self.tr("Load ENC depth areas (DEPARE)")

    def shortHelpString(self):  # pylint: disable=invalid-name
        return self.tr(
            "Loads the DEPARE (depth area) layer of all S-57 (.000) files in a folder into a new layer group "
            "and styles it with a blue gradient on DRVAL1 (negative values in purple).\n\n"
            "<b>Source mode</b>\n"
            "• Read S-57 files directly: one layer per .000 file (slow to render with many files).\n"
            "• Convert to GeoParquet, then load (recommended): files are converted once, spatially sorted "
            "and cached; subsequent runs reuse up-to-date files.\n\n"
            "<b>GeoParquet layout</b>: one merged file (single layer, fastest) or one file per source file.\n\n"
            "<b>GeoParquet location</b>: in memory (lost when QGIS closes; not saved with the project), "
            "next to the source files, the system temp folder, or a custom folder."
        )

    def initAlgorithm(self, config=None):  # pylint: disable=invalid-name
        self.addParameter(
            QgsProcessingParameterFile(
                self.INPUT_FOLDER,
                self.tr("Folder with S-57 (.000) files"),
                behavior=Qgis.ProcessingFileParameterBehavior.Folder,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.RECURSIVE, self.tr("Include subfolders"), defaultValue=False
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.SOURCE_MODE,
                self.tr("Source mode"),
                options=[
                    self.tr("Read S-57 files directly"),
                    self.tr("Convert to GeoParquet, then load (recommended)"),
                ],
                defaultValue=MODE_PARQUET,
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PARQUET_LAYOUT,
                self.tr("GeoParquet layout"),
                options=[self.tr(o) for o in LAYOUT_LABELS],
                defaultValue=int(Layout.MERGED),
            )
        )
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PARQUET_LOCATION,
                self.tr("GeoParquet location"),
                options=[self.tr(o) for o in LOCATION_LABELS],
                defaultValue=int(Location.SOURCE),
            )
        )
        self.addParameter(
            QgsProcessingParameterFile(
                self.PARQUET_FOLDER,
                self.tr("Custom GeoParquet folder (when location is 'Custom folder')"),
                behavior=Qgis.ProcessingFileParameterBehavior.Folder,
                optional=True,
            )
        )

        advanced = [
            QgsProcessingParameterBoolean(
                self.REUSE_EXISTING,
                self.tr("Reuse up-to-date GeoParquet files"),
                defaultValue=True,
            ),
            QgsProcessingParameterString(
                self.GROUP_NAME,
                self.tr("Layer group name (default: input folder)"),
                optional=True,
            ),
            QgsProcessingParameterBoolean(
                self.APPLY_STYLE, self.tr("Apply depth style"), defaultValue=True
            ),
            QgsProcessingParameterNumber(
                self.MIN_DEPTH,
                self.tr("Style: minimum depth (m)"),
                Qgis.ProcessingNumberParameterType.Double,
                defaultValue=0.0,
            ),
            QgsProcessingParameterNumber(
                self.MAX_DEPTH,
                self.tr("Style: maximum depth (m)"),
                Qgis.ProcessingNumberParameterType.Double,
                defaultValue=7.0,
            ),
            QgsProcessingParameterNumber(
                self.CLASSES,
                self.tr("Style: number of classes"),
                Qgis.ProcessingNumberParameterType.Integer,
                defaultValue=14,
                minValue=1,
                maxValue=100,
            ),
        ]
        for param in advanced:
            param.setFlags(param.flags() | Qgis.ProcessingParameterFlag.Advanced)
            self.addParameter(param)

        self.addOutput(
            QgsProcessingOutputMultipleLayers(
                self.OUTPUT_LAYERS, self.tr("Loaded layers")
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.PARQUET_FILES, self.tr("GeoParquet files (';'-separated)")
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                self.LAYER_COUNT, self.tr("Number of loaded layers")
            )
        )

    def checkParameterValues(self, parameters, context):  # pylint: disable=invalid-name
        ok, msg = super().checkParameterValues(parameters, context)
        if not ok:
            return ok, msg
        if self.parameterAsEnum(parameters, self.SOURCE_MODE, context) == MODE_PARQUET:
            location = self.parameterAsEnum(parameters, self.PARQUET_LOCATION, context)
            if location == Location.CUSTOM and not self.parameterAsFile(
                parameters, self.PARQUET_FOLDER, context
            ):
                return False, self.tr(
                    "Select a custom GeoParquet folder, or choose another GeoParquet location."
                )
            if not parquet_driver_available():
                return False, self.tr(
                    "The GDAL Parquet driver is not available; use 'Read S-57 files directly'."
                )
        if self.parameterAsDouble(
            parameters, self.MAX_DEPTH, context
        ) <= self.parameterAsDouble(parameters, self.MIN_DEPTH, context):
            return False, self.tr("Maximum depth must be greater than minimum depth.")
        return True, ""

    def processAlgorithm(self, parameters, context, feedback):  # pylint: disable=invalid-name
        folder = self.parameterAsFile(parameters, self.INPUT_FOLDER, context)
        if not folder or not os.path.isdir(folder):
            raise QgsProcessingException(
                self.tr("Input folder does not exist: {}").format(folder)
            )
        folder = os.path.abspath(folder)
        recursive = self.parameterAsBool(parameters, self.RECURSIVE, context)
        mode = self.parameterAsEnum(parameters, self.SOURCE_MODE, context)

        self._to_load = []
        self._group_name = (
            self.parameterAsString(parameters, self.GROUP_NAME, context).strip()
            or folder
        )
        self._style = None
        if self.parameterAsBool(parameters, self.APPLY_STYLE, context):
            self._style = (
                self.parameterAsDouble(parameters, self.MIN_DEPTH, context),
                self.parameterAsDouble(parameters, self.MAX_DEPTH, context),
                self.parameterAsInt(parameters, self.CLASSES, context),
            )

        sources = find_s57_files(folder, recursive)
        if not sources:
            raise QgsProcessingException(
                self.tr("No .000 files found in {}").format(folder)
            )
        feedback.pushInfo(self.tr("Found {} S-57 file(s)").format(len(sources)))

        parquet_files = []
        if mode == MODE_DIRECT:
            for i, source in enumerate(sources):
                if feedback.isCanceled():
                    return {}
                if has_layer(source.path, DEPARE):
                    self._to_load.append(
                        (
                            f"{source.path}|layername={DEPARE}",
                            f"{source.relpath} - {DEPARE}",
                        )
                    )
                else:
                    feedback.pushInfo(
                        self.tr("No DEPARE layer in {}").format(source.relpath)
                    )
                feedback.setProgress(100 * (i + 1) / len(sources))
        else:
            layout = Layout(
                self.parameterAsEnum(parameters, self.PARQUET_LAYOUT, context)
            )
            location = Location(
                self.parameterAsEnum(parameters, self.PARQUET_LOCATION, context)
            )
            output_folder = resolve_output_folder(
                location,
                folder,
                recursive,
                self.parameterAsFile(parameters, self.PARQUET_FOLDER, context),
            )
            reuse = self.parameterAsBool(parameters, self.REUSE_EXISTING, context)
            feedback.pushInfo(self.tr("GeoParquet folder: {}").format(output_folder))
            if location == Location.MEMORY:
                feedback.pushWarning(
                    self.tr(
                        "In-memory GeoParquet layers are lost when QGIS closes and cannot be restored from a saved project."
                    )
                )
            try:
                result = convert_sources(
                    sources, folder, output_folder, layout, reuse, feedback=feedback
                )
            except ConversionCanceled:
                feedback.pushWarning(self.tr("Conversion canceled"))
                return {}
            except RuntimeError as err:
                raise QgsProcessingException(str(err)) from err
            report_result(self, result, feedback)
            parquet_files = result.files
            if layout == Layout.MERGED:
                label = os.path.basename(os.path.normpath(folder))
                self._to_load = [
                    (path, f"{label} - {DEPARE}") for path in parquet_files
                ]
            else:
                by_path = {
                    per_file_output_path(output_folder, source): source
                    for source in sources
                }
                self._to_load = [
                    (path, f"{by_path[path].relpath} - {DEPARE}")
                    for path in parquet_files
                ]

        if not self._to_load:
            feedback.pushWarning(self.tr("No DEPARE layers found; nothing to load."))
        return {self.PARQUET_FILES: ";".join(parquet_files)}

    def postProcessAlgorithm(self, context, feedback):  # pylint: disable=invalid-name
        """Runs in the main thread: create, style and add the layers to a new group."""
        project = context.project() or QgsProject.instance()
        layer_ids = []
        if self._to_load:
            group = project.layerTreeRoot().insertGroup(0, self._group_name)
            options = QgsVectorLayer.LayerOptions(project.transformContext())
            options.forceReadOnly = True
            for uri, name in self._to_load:
                layer = QgsVectorLayer(uri, name, "ogr", options)
                if not layer.isValid():
                    feedback.reportError(
                        self.tr("Failed to load {}").format(uri), False
                    )
                    continue
                if self._style is not None:
                    min_depth, max_depth, classes = self._style
                    apply_depth_renderer(
                        layer, min_val=min_depth, max_val=max_depth, intervals=classes
                    )
                project.addMapLayer(layer, False)
                group.addLayer(layer)
                layer_ids.append(layer.id())
            feedback.pushInfo(
                self.tr("Added {} layer(s) to group '{}'").format(
                    len(layer_ids), self._group_name
                )
            )
        self._to_load = []
        return {self.OUTPUT_LAYERS: layer_ids, self.LAYER_COUNT: len(layer_ids)}

    def flags(self):
        return super().flags() | Qgis.ProcessingAlgorithmFlag.RequiresProject
