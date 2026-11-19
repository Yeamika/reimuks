#!/usr/bin/env python3
"""Build the Wayland and Vulkan test-app overlay."""
from pathlib import Path
import sys

LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[2]/'scripts'))
from app_overlay import main


if __name__ == '__main__':
    main('gui-test', ['glmark2-wayland', 'glmark2-es2-wayland', 'vulkan-tools'])
