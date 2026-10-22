#!/usr/bin/env python3
"""Build the self-contained installer payload from reviewable source modules."""
import argparse
import ast
import json
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
    catalog=json.loads((ROOT/'data/warp-rules.json').read_text())
    tree=ast.parse((ROOT/'src/warp.py').read_text())
    values={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('MEDIA','AI','RULE_VERSION')}
    if catalog['media']!=values['MEDIA'] or catalog['ai']!=values['AI'] or catalog['version']!=values['RULE_VERSION']:parser.exit(1,'WARP catalog and source defaults differ\n')
    bootstrap=assemble('bootstrap.sh')
    for source,filename in [('manager.sh','singbox-v2.sh'),('installer.sh','install.sh'),('bootstrap.sh','bootstrap.sh')]:
        result = assemble(source)
        target = ROOT / filename
        if args.check:
            if target.read_text() != result:
                parser.exit(1, filename+' is stale; run python3 scripts/build.py\n')
        else:
            target.write_text(result)
    start='<!-- SKYBYTE_INSTALL_COMMAND_START -->'
    end='<!-- SKYBYTE_INSTALL_COMMAND_END -->'
    command=start+'\n```bash\n'+bootstrap+'```\n'+end
    for filename in ['README.md','README_EN.md']:
        target=ROOT/filename
        original=target.read_text()
        if original.count(start)!=1 or original.count(end)!=1:
            parser.exit(1,filename+' must contain one installation command block\n')
        result=re.sub(re.escape(start)+r'.*?'+re.escape(end),lambda match:command,original,flags=re.S)
        if args.check:
            if original!=result:parser.exit(1,filename+' installation command is stale; run python3 scripts/build.py\n')
        else:
            target.write_text(result)


if __name__ == '__main__':
    main()
