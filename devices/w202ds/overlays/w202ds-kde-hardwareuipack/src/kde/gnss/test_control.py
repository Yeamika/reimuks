"""Native GNSS and shared-control regression entry point."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[7] / 'tests'))
from test_desktop_controls import NativeControlsTest
if __name__ == '__main__':
    unittest.main()
