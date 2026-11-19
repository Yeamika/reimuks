#!/usr/bin/env python3
"""Build the remote-work and streaming-client App overlay."""
from pathlib import Path
import sys

LAYER = Path(__file__).resolve().parent
sys.path.insert(0, str(LAYER.parents[2]/'scripts'))
from app_overlay import main


if __name__ == '__main__':
    main('remote', ['code', 'google-chrome-stable', 'moonlight-qt'],
         keyrings=('/usr/share/keyrings/reimuks-google.asc',
                   '/usr/share/keyrings/reimuks-microsoft.asc',
                   '/usr/share/keyrings/reimuks-moonlight.asc'),
         files=LAYER/'files', configure=LAYER/'configure.py')
