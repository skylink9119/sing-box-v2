"""Conservative read-only gate before automatically enabling a new firewall."""
import json
import re
import shutil
import subprocess
import sys


def nft_clean(text):
    data=json.loads(text)
    if not isinstance(data,dict) or not isinstance(data.get('nftables'),list):
        return False
    for item in data['nftables']:
        if not isinstance(item,dict) or len(item)!=1:
            return False
        kind,value=next(iter(item.items()))
        if not isinstance(value,dict):
            return False
        if kind in ('metainfo','table'):
            continue
        if kind=='chain' and value.get('policy')=='accept':
            continue
        return False
    return True


def iptables_clean(text):
    for line in text.splitlines():
        if not line or line.startswith('#') or line=='COMMIT' or line.startswith('*'):
            continue
        if re.fullmatch(r':(?:INPUT|OUTPUT|FORWARD|PREROUTING|POSTROUTING) ACCEPT \[\d+:\d+\]',line):
            continue
        return False
    return True


def check():
    if shutil.which('firewall-cmd'):
        result=subprocess.run(['firewall-cmd','--state'],capture_output=True,text=True,timeout=5)
        if result.returncode==0:
            raise ValueError('firewalld is active / firewalld 已启用，请人工管理')
    if not shutil.which('nft'):
        raise ValueError('nft is unavailable; cannot inspect rules / 缺少 nft，无法核对现有规则')
    commands=[(['nft','-j','list','ruleset'],nft_clean)]
    for name in ('iptables-save','ip6tables-save','iptables-legacy-save','ip6tables-legacy-save'):
        if shutil.which(name):commands.append(([name],iptables_clean))
    for arguments,validate in commands:
        result=subprocess.run(arguments,capture_output=True,text=True,timeout=5)
        if result.returncode or not validate(result.stdout):
            raise ValueError('Existing or unreadable firewall rules; use manual UFW controls / 已有规则或无法读取规则，请用 d → 2 人工核对后启用')


if __name__=='__main__':
    try:check()
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print(str(error),file=sys.stderr);sys.exit(1)
