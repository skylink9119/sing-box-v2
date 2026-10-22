#!/usr/bin/env python3
"""Package explicit public release assets; never include runtime state or credentials."""
import argparse,hashlib,pathlib,re,shutil,subprocess
ROOT=pathlib.Path(__file__).resolve().parents[1]
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True);args=parser.parse_args();out=pathlib.Path(args.output)
 if out.exists() or out.is_symlink():parser.error('Output must be a new directory')
 subprocess.run(['python3',str(ROOT/'scripts/build.py'),'--check'],check=True)
 subprocess.run(['bash',str(ROOT/'singbox-v2.sh'),'--self-check'],check=True)
 version=re.search(r'^MANAGER_VERSION=(.+)$',(ROOT/'src/manager.sh').read_text(),re.M)[1]
 out.mkdir(parents=True,mode=0o700)
 assets={'bootstrap.sh':ROOT/'bootstrap.sh','install.sh':ROOT/'install.sh','singbox-v2.sh':ROOT/'singbox-v2.sh','warp-rules.json':ROOT/'data/warp-rules.json'}
 for name,source in assets.items():shutil.copyfile(source,out/name)
 (out/'SHA256SUMS').write_text(''.join(hashlib.sha256((out/name).read_bytes()).hexdigest()+'  '+name+'\n' for name in sorted(assets)))
 print('Prepared SKYBYTE Manager v'+version+' assets: '+str(out))
if __name__=='__main__':main()
