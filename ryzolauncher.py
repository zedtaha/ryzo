#!/usr/bin/env python3
"""Run Ryzo from a source checkout without installing it."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ryzo.__main__ import main  # noqa: E402

main()
