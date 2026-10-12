#!/usr/bin/env python3
"""Build the self-contained installer payload from reviewable source modules."""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def assemble(name, chain=()):
    if name in chain:
        raise ValueError('Recursive source include: ' + name)
    path = ROOT / 'src' / name
    if path.parent != ROOT / 'src':
        raise ValueError('Invalid source include')
    source = path.read_text()
    return re.sub(r'^# @include ([a-z_]+\.(?:sh|py))\n',
                  lambda match: assemble(match[1], chain + (name,)), source, flags=re.M)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    result = assemble('manager.sh')
    target = ROOT / 'singbox-v2.sh'
    if args.check:
        if target.read_text() != result:
            parser.exit(1, 'singbox-v2.sh is stale; run python3 scripts/build.py\n')
    else:
        target.write_text(result)


if __name__ == '__main__':
    main()
