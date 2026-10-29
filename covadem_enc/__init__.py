"""CoVadem ENC QGIS plugin: load S-57 (ENC) depth areas, optionally via GeoParquet."""

__author__ = "CoVadem"
__copyright__ = "(C) 2026 by CoVadem"


def classFactory(iface):  # pylint: disable=invalid-name
    from .plugin import CovademEncPlugin

    return CovademEncPlugin(iface)
