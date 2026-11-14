"""Ryzo - an interactive editor for R, modelled after Pyzo.

Ryzo combines a code editor, interactive R shells and a set of tools
(file browser, workspace, plots, help, source structure, history) in a
single window. It aims to be simple and interactive, the way Pyzo is
for Python.
"""

import os

__version__ = "0.1.0"

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
KERNEL_SCRIPT = os.path.join(PACKAGE_DIR, "kernel", "ryzo_kernel.R")
RESOURCE_DIR = os.path.join(PACKAGE_DIR, "resources")
