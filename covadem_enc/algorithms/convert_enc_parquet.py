import os

from qgis.core import (
    Qgis,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterEnum,
    QgsProcessingParameterFile,
    QgsProcessingParameterFolderDestination,
)

from ..core.parquet import (
    LAYOUT_LABELS,
    ConversionCanceled,
    Layout,
    convert_sources,
    parquet_driver_available,
)
from ..core.s57 import find_s57_files
from .base import CovademEncAlgorithm


class ConvertEncToParquetAlgorithm(CovademEncAlgorithm):
    INPUT_FOLDER = "INPUT_FOLDER"
    RECURSIVE = "RECURSIVE"
    LAYOUT = "LAYOUT"
    OVERWRITE = "OVERWRITE"
    OUTPUT_FOLDER = "OUTPUT_FOLDER"
    OUTPUT_FILES = "OUTPUT_FILES"
    CONVERTED = "CONVERTED"
    REUSED = "REUSED"
    FEATURES = "FEATURES"

    def name(self):
        return "convert_enc_to_parquet"

    def displayName(self):  # pylint: disable=invalid-name
        return self.tr("Convert ENC to GeoParquet")

    def shortHelpString(self):  # pylint: disable=invalid-name
        return self.tr(
            "Converts the DEPARE (depth area) layer of all S-57 (.000) files in a folder to GeoParquet.\n\n"
            "• One merged file: a single GeoParquet file with a 'source_file' column. Fastest to render.\n"
            "• One file per source: <cell>_DEPARE.parquet for each .000 file.\n\n"
            "Files are spatially sorted and ZSTD-compressed. Unless 'Overwrite' is checked, up-to-date "
            "outputs are reused. Use 'Load ENC depth areas (DEPARE)' to load them styled."
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
                self.LAYOUT,
                self.tr("GeoParquet layout"),
                options=[self.tr(o) for o in LAYOUT_LABELS],
                defaultValue=0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.OVERWRITE,
                self.tr("Overwrite existing up-to-date files"),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.OUTPUT_FOLDER, self.tr("Output folder")
            )
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.OUTPUT_FILES, self.tr("GeoParquet files (';'-separated)")
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(self.CONVERTED, self.tr("Converted files"))
        )
        self.addOutput(QgsProcessingOutputNumber(self.REUSED, self.tr("Reused files")))
        self.addOutput(
            QgsProcessingOutputNumber(self.FEATURES, self.tr("Converted features"))
        )

    def processAlgorithm(self, parameters, context, feedback):  # pylint: disable=invalid-name
        if not parquet_driver_available():
            raise QgsProcessingException(
                self.tr(
                    "The GDAL Parquet driver is not available in this QGIS installation."
                )
            )
        folder = self.parameterAsFile(parameters, self.INPUT_FOLDER, context)
        if not folder or not os.path.isdir(folder):
            raise QgsProcessingException(
                self.tr("Input folder does not exist: {}").format(folder)
            )
        recursive = self.parameterAsBool(parameters, self.RECURSIVE, context)
        layout = Layout(self.parameterAsEnum(parameters, self.LAYOUT, context))
        overwrite = self.parameterAsBool(parameters, self.OVERWRITE, context)
        output_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)

        sources = find_s57_files(folder, recursive)
        if not sources:
            raise QgsProcessingException(
                self.tr("No .000 files found in {}").format(folder)
            )
        feedback.pushInfo(self.tr("Found {} S-57 file(s)").format(len(sources)))

        try:
            result = convert_sources(
                sources, folder, output_folder, layout, not overwrite, feedback=feedback
            )
        except ConversionCanceled:
            feedback.pushWarning(self.tr("Conversion canceled"))
            return {}
        except RuntimeError as err:
            raise QgsProcessingException(str(err)) from err

        report_result(self, result, feedback)
        return {
            self.OUTPUT_FOLDER: output_folder,
            self.OUTPUT_FILES: ";".join(result.files),
            self.CONVERTED: result.converted,
            self.REUSED: result.reused,
            self.FEATURES: result.features,
        }


def report_result(alg, result, feedback):
    feedback.pushInfo(
        alg.tr("GeoParquet: {} converted, {} reused, {} features written").format(
            result.converted, result.reused, result.features
        )
    )
    if result.no_layer:
        feedback.pushInfo(
            alg.tr("{} file(s) without DEPARE layer skipped").format(
                len(result.no_layer)
            )
        )
    if result.skipped_geometries:
        feedback.pushWarning(
            alg.tr("{} non-polygon/empty DEPARE feature(s) skipped").format(
                result.skipped_geometries
            )
        )
    if result.warnings:
        feedback.pushInfo(
            alg.tr("{} GDAL warning(s) while reading S-57 data").format(result.warnings)
        )
    for relpath in result.failed:
        feedback.reportError(alg.tr("Failed: {}").format(relpath), False)
