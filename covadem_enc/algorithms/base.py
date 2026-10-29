from qgis.core import QgsProcessingAlgorithm
from qgis.PyQt.QtCore import QCoreApplication


class CovademEncAlgorithm(QgsProcessingAlgorithm):
    def group(self):
        return self.tr("ENC (S-57)")

    def groupId(self):  # pylint: disable=invalid-name
        return "enc"

    def tr(self, string):
        return QCoreApplication.translate("CovademEnc", string)

    def createInstance(self):  # pylint: disable=invalid-name
        return type(self)()
