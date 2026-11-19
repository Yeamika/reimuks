#!/usr/bin/env python3
"""List registered board layers and the profiles that select them."""
import argparse
import json
import sys
from overlay_registry import catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', required=True)
    args = parser.parse_args()
    try:
        result = catalog(args.board)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
