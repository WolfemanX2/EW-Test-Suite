# -*- coding: utf-8 -*-
"""Runs every test_*.py in this folder, outside Revit:  python tests/run_tests.py

The tests use Python 3 and the stand-ins in revit_stand_ins.py instead of Revit, so they check the libraries' own
logic (settings files, tracing order, helpers), not what Revit does with the result. pyRevit ignores this folder."""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(HERE, pattern="test_*.py", top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
