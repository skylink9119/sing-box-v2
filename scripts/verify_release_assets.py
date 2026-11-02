#!/usr/bin/env python3
"""Require published release bytes to match the build before signing provenance."""
import argparse
import hashlib
from pathlib import Path

ASSETS = ('bootstrap.sh', 'install.sh', 'singbox-v2.sh', 'warp-rules.json', 'SHA256SUMS')

def verify(built, published):
    for name in ASSETS:
        expected, actual = built / name, published / name
        if (not expected.is_file() or not actual.is_file() or
                expected.is_symlink() or actual.is_symlink() or
                hashlib.sha256(expected.read_bytes()).digest() != hashlib.sha256(actual.read_bytes()).digest()):
            raise ValueError('Release asset differs from tagged build: ' + name)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('built', type=Path)
    parser.add_argument('published', type=Path)
    args = parser.parse_args()
    verify(args.built, args.published)
    print('All published assets match the tagged build')

if __name__ == '__main__':
    main()
