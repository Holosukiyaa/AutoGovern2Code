from __future__ import annotations

import os
import atexit
import shutil
import sys
import tempfile
from pathlib import Path


SOURCE_ROOT = str(Path(__file__).resolve().parents[1] / "src")
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

python_path = os.environ.get("PYTHONPATH", "")
python_path_entries = [entry for entry in python_path.split(os.pathsep) if entry]
if SOURCE_ROOT not in python_path_entries:
    os.environ["PYTHONPATH"] = os.pathsep.join([SOURCE_ROOT, *python_path_entries])

if "AG2C_DATA_ROOT" not in os.environ:
    _TEST_DATA_ROOT = tempfile.mkdtemp(prefix="ag2c-tests-")
    os.environ["AG2C_DATA_ROOT"] = _TEST_DATA_ROOT
    atexit.register(shutil.rmtree, _TEST_DATA_ROOT, ignore_errors=True)
if "AG2C_PORTABLE" not in os.environ:
    os.environ["AG2C_PORTABLE"] = "0"
