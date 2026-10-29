"""DEPARE depth styling (graduated `Blues` ramp on DRVAL1), ported from AddEncMaps.py."""

from qgis.core import (
    QgsClassificationCustom,
    QgsFillSymbol,
    QgsGraduatedSymbolRenderer,
    QgsRendererRange,
    QgsSimpleFillSymbolLayer,
    QgsStyle,
    QgsSymbol,
)
from qgis.PyQt.QtGui import QColor

STROKE_COLOR = QColor(16, 16, 32)
STROKE_WIDTH = 0.06
INVALID_COLOR = QColor(255, 0, 255)
INVALID_LOWER_BOUND = -10


def create_symbol(layer, color):
    symbol = QgsSymbol.defaultSymbol(layer.geometryType())
    symbol.setColor(color)
    if isinstance(symbol, QgsFillSymbol):
        for symbol_layer in symbol.symbolLayers():
            if isinstance(symbol_layer, QgsSimpleFillSymbolLayer):
                symbol_layer.setStrokeColor(STROKE_COLOR)
                symbol_layer.setStrokeWidth(STROKE_WIDTH)
    return symbol


def apply_depth_renderer(layer, field="DRVAL1", min_val=0.0, max_val=7.0, intervals=14):
    color_ramp = QgsStyle.defaultStyle().colorRamp("Blues")
    range_size = (max_val - min_val) / intervals

    ranges = [
        QgsRendererRange(
            INVALID_LOWER_BOUND,
            min_val,
            create_symbol(layer, INVALID_COLOR),
            f"{INVALID_LOWER_BOUND:.1f} - {min_val:.1f}",
        )
    ]
    for i in range(intervals):
        lower = min_val + i * range_size
        upper = lower + range_size
        ranges.append(
            QgsRendererRange(lower, upper, create_symbol(layer, color_ramp.color(i / intervals)), f"{lower:.1f} - {upper:.1f}")
        )
    ranges.append(
        QgsRendererRange(max_val, max_val * 10, create_symbol(layer, color_ramp.color(1)), f"{max_val:.1f} - {max_val * 10:.1f}")
    )

    renderer = QgsGraduatedSymbolRenderer(field, ranges)
    renderer.setSourceColorRamp(color_ramp)
    renderer.setClassificationMethod(QgsClassificationCustom())
    layer.setRenderer(renderer)
