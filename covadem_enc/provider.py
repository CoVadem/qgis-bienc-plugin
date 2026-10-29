import os

from qgis.core import QgsProcessingProvider
from qgis.PyQt.QtGui import QIcon

from .algorithms.convert_enc_parquet import ConvertEncToParquetAlgorithm
from .algorithms.load_enc_depare import LoadEncDepareAlgorithm

PLUGIN_DIR = os.path.dirname(__file__)


class CovademEncProvider(QgsProcessingProvider):
    def loadAlgorithms(self):  # pylint: disable=invalid-name
        self.addAlgorithm(LoadEncDepareAlgorithm())
        self.addAlgorithm(ConvertEncToParquetAlgorithm())

    def id(self):
        return "covadem_enc"

    def name(self):
        return self.tr("CoVadem ENC")

    def longName(self):  # pylint: disable=invalid-name
        return self.name()

    def icon(self):
        return QIcon(os.path.join(PLUGIN_DIR, "icon.svg"))
