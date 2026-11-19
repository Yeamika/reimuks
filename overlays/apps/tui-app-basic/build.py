#!/usr/bin/env python3
"""Build the basic terminal-app overlay."""
from pathlib import Path
import sys

LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[2]/'scripts'))
from app_overlay import main


if __name__ == '__main__':
    main('tui-app-basic', ['btop', 'vim', 'lazygit', 'fastfetch'])
