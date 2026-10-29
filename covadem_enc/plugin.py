from qgis.core import QgsApplication

from .provider import CovademEncProvider


class CovademEncPlugin:
    def __init__(self, iface=None):
        self.iface = iface
        self.provider = None

    def initProcessing(self):  # pylint: disable=invalid-name
        self.provider = CovademEncProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def initGui(self):  # pylint: disable=invalid-name
        self.initProcessing()

    def unload(self):
        if self.provider is not None:
            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
