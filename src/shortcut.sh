# Own only /usr/local/bin/sb; never replace the system lrzsz sender at /usr/bin/sb.
MANAGER_SHORTCUT=${MANAGER_SHORTCUT:-/usr/local/bin/sb}
SB_FILE_SENDER=${SB_FILE_SENDER:-/usr/bin/sb}
manager_shortcut_install(){
 require_cmd python3 || return 1
 python3 - "$SCRIPT_PATH" "$MANAGER_LIB" "$MANAGER_SHORTCUT" "$SB_FILE_SENDER" <<'PY_SHORTCUT'
import os,pathlib,shlex,subprocess,sys,tempfile
source,target,shortcut,sender=map(pathlib.Path,sys.argv[1:])
marker='# SKYBYTE Manager shortcut v1\n'
for p in (target,shortcut):
 if not p.is_absolute() or any(x.is_symlink() for x in (p,*p.parents)):
  raise SystemExit('Unsafe shortcut path / 快捷入口路径异常')
 if p.exists() and not p.is_file():raise SystemExit('Existing path is not a regular file')
if shortcut.exists() and not shortcut.read_text().startswith('#!/usr/bin/env bash\n'+marker):
 raise SystemExit('Existing sb command preserved / 已有 sb 命令非本工具，已保留')
if target.exists() and not any(line.startswith('# SKYBYTE Manager V2.1 community manager;') for line in target.read_text().splitlines()[:4]):
 raise SystemExit('Existing manager is not owned / 已有管理脚本归属异常')
if source.is_symlink() or not source.is_file():raise SystemExit('Invalid source manager')
if not any(line.startswith('# SKYBYTE Manager V2.1 community manager;') for line in source.read_text().splitlines()[:4]):raise SystemExit('Unknown source manager')
if not sender.is_absolute() or sender==shortcut:raise SystemExit('Invalid file-sender path')
if subprocess.run(['bash','-n',str(source)]).returncode:raise SystemExit('Invalid manager syntax')
def atomic(p,data,mode):
 p.parent.mkdir(parents=True,exist_ok=True)
 fd,name=tempfile.mkstemp(prefix='.skybyte-',dir=p.parent)
 try:
  os.fchmod(fd,mode)
  with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(name,p)
 finally:
  if os.path.exists(name):os.unlink(name)
if source.absolute()!=target.absolute():atomic(target,source.read_bytes(),0o700)
# lrzsz is still available with arguments. Nothing changes /usr/bin/sb.
wrapper='#!/usr/bin/env bash\n'+marker+'set -e\n'
wrapper+='if (( $# )); then\n if [[ -x '+shlex.quote(str(sender))+' ]]; then exec '+shlex.quote(str(sender))+' "$@"; fi\n'
wrapper+=' printf "sb opens SKYBYTE Manager; original file sender unavailable\\n" >&2\n exit 2\nfi\n'
wrapper+='exec bash '+shlex.quote(str(target))+'\n'
atomic(shortcut,wrapper.encode(),0o755)
PY_SHORTCUT
}
manager_shortcut_remove(){
 [[ ! -L $MANAGER_SHORTCUT ]] || return 0
 if [[ -f $MANAGER_SHORTCUT ]] && grep -Fxq '# SKYBYTE Manager shortcut v1' "$MANAGER_SHORTCUT";then rm -f -- "$MANAGER_SHORTCUT";fi
}
