"""Headless integration test for the CoVadem ENC plugin.

Run with the QGIS Python, e.g.:
    "C:\\Program Files\\QGIS 4.2.2\\bin\\python-qgis.bat" tests\\test_algorithms.py <folder-with-000-files>
"""

import os
import shutil
import sys
import tempfile
import time

from qgis.core import QgsApplication, QgsGraduatedSymbolRenderer, QgsProject

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

app = QgsApplication([], False)
app.initQgis()
sys.path.append(os.path.join(QgsApplication.pkgDataPath(), "python", "plugins"))

from processing.core.Processing import Processing  # noqa: E402  pylint: disable=wrong-import-position
from processing.tools import dataobjects  # noqa: E402  pylint: disable=wrong-import-position

import processing  # noqa: E402  pylint: disable=wrong-import-position
from covadem_enc.provider import CovademEncProvider  # noqa: E402  pylint: disable=wrong-import-position

Processing.initialize()
provider = CovademEncProvider()
QgsApplication.processingRegistry().addProvider(provider)

LOAD = "covadem_enc:load_enc_depare"
CONVERT = "covadem_enc:convert_enc_to_parquet"


def feature_total(layer_ids):
    project = QgsProject.instance()
    return sum(project.mapLayer(lid).featureCount() for lid in layer_ids)


def run_load(folder, **params):
    QgsProject.instance().clear()
    started = time.perf_counter()
    result = processing.run(LOAD, {"INPUT_FOLDER": folder, **params})
    elapsed = time.perf_counter() - started
    ids = result["OUTPUT_LAYERS"]
    project = QgsProject.instance()
    for lid in ids:
        layer = project.mapLayer(lid)
        assert layer.isValid(), lid
        assert isinstance(layer.renderer(), QgsGraduatedSymbolRenderer), lid
    group = project.layerTreeRoot().children()[0]
    assert len(group.findLayers()) == len(ids)
    return ids, elapsed


def main(folder):
    assert QgsApplication.processingRegistry().providerById("covadem_enc").name() == "CoVadem ENC"
    tmp = tempfile.mkdtemp(prefix="covadem_enc_test_")
    try:
        ids, t = run_load(folder, SOURCE_MODE=0)
        direct_count = feature_total(ids)
        print(f"direct: {len(ids)} layers, {direct_count} features, {t:.1f}s")
        assert ids and direct_count > 0

        custom = os.path.join(tmp, "custom")
        cases = [
            ("memory/merged", {"PARQUET_LOCATION": 0, "PARQUET_LAYOUT": 0}),
            ("memory/per-file", {"PARQUET_LOCATION": 0, "PARQUET_LAYOUT": 1}),
            ("temp/merged", {"PARQUET_LOCATION": 2, "PARQUET_LAYOUT": 0, "REUSE_EXISTING": False}),
            ("custom/merged", {"PARQUET_LOCATION": 3, "PARQUET_LAYOUT": 0, "PARQUET_FOLDER": custom}),
            ("custom/merged reuse", {"PARQUET_LOCATION": 3, "PARQUET_LAYOUT": 0, "PARQUET_FOLDER": custom}),
            ("custom/per-file", {"PARQUET_LOCATION": 3, "PARQUET_LAYOUT": 1, "PARQUET_FOLDER": custom}),
            ("custom/per-file reuse", {"PARQUET_LOCATION": 3, "PARQUET_LAYOUT": 1, "PARQUET_FOLDER": custom}),
        ]
        for label, params in cases:
            ids, t = run_load(folder, SOURCE_MODE=1, **params)
            count = feature_total(ids)
            print(f"{label}: {len(ids)} layers, {count} features, {t:.1f}s")
            assert count == direct_count, (label, count, direct_count)
            if params["PARQUET_LAYOUT"] == 0:
                assert len(ids) == 1

        alg = QgsApplication.processingRegistry().createAlgorithmById(LOAD)
        ok, _msg = alg.checkParameterValues(
            {"INPUT_FOLDER": folder, "SOURCE_MODE": 1, "PARQUET_LOCATION": 3}, dataobjects.createContext()
        )
        assert not ok, "custom location without folder must be rejected"

        out = os.path.join(tmp, "convert")
        res = processing.run(CONVERT, {"INPUT_FOLDER": folder, "LAYOUT": 1, "OUTPUT_FOLDER": out})
        print(f"convert per-file: {res['CONVERTED']} converted, {res['FEATURES']} features")
        assert res["FEATURES"] == direct_count
        res = processing.run(CONVERT, {"INPUT_FOLDER": folder, "LAYOUT": 1, "OUTPUT_FOLDER": out})
        assert res["CONVERTED"] == 0 and res["REUSED"] > 0
        print("ALL TESTS PASSED")
    finally:
        QgsProject.instance().clear()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1])
    app.exitQgis()
