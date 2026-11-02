#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
if [[ -t 2 && -z ${NO_COLOR:-} ]]; then RED=$'\033[1;31m'; RESET=$'\033[0m'; else RED=''; RESET=''; fi
err(){ printf '%s%s%s\n' "$RED" "$*" "$RESET" >&2; }
RELEASE_VERSION=@MANAGER_VERSION@
MANAGER_SHA256=@MANAGER_SHA256@
RELEASE_URL=https://github.com/skylink9119/sing-box-v2/releases/download/v$RELEASE_VERSION
URL=$RELEASE_URL/singbox-v2.sh
MANAGER_DIR=/usr/local/lib/singbox-v2
MANAGER_TARGET=$MANAGER_DIR/singbox-v2.sh
MANAGER_LOCK=/run/singbox-v2.lock
OS_RELEASE=${OS_RELEASE:-/etc/os-release}
L(){ printf '%s / %s' "$1" "$2"; }
warn(){ printf '%s\n' "$*" >&2; }
# @include lib/packages.sh
installer_dependencies(){
 local name
 local missing=()
 for name in curl flock python3;do command -v "$name" >/dev/null || missing+=("$name");done
 if (( ${#missing[@]} ));then
  warn "Missing tools: ${missing[*]}; installing base dependencies / 缺少工具：${missing[*]}，正在自动安装基础依赖"
  apt_install --no-install-recommends curl ca-certificates python3 util-linux || return 1
 fi
 for name in curl flock python3;do command -v "$name" >/dev/null || { err "Missing $name after installation / 安装后仍缺少 $name";return 1; };done
}
installer_guard(){
 [[ ! -L $MANAGER_DIR && ( ! -e $MANAGER_DIR || -d $MANAGER_DIR ) && ! -L $MANAGER_TARGET && ! -L $MANAGER_LOCK && ( ! -e $MANAGER_LOCK || -f $MANAGER_LOCK ) ]] || { err 'Unsafe installer path / 安装路径异常'; return 1; }
 if [[ -e $MANAGER_TARGET ]];then
  if [[ ! -f $MANAGER_TARGET ]] || ! grep -q '^# SKYBYTE Manager V2.1 community manager;' "$MANAGER_TARGET";then err 'Existing file is not SKYBYTE Manager / 已有文件不属于 SKYBYTE Manager';return 1;fi
 fi
}
installer_launch(){ exec 9>&-;exec bash "$MANAGER_TARGET"; }
installer_root(){ if (( EUID != 0 ));then err 'Please run as root / 请使用 root';return 1;fi; }
installer_verify(){
 python3 - "$1" "$2" "$MANAGER_TARGET" "$RELEASE_VERSION" "$MANAGER_SHA256" <<'PY_INSTALLER_VERIFY'
import hashlib,pathlib,re,sys
payload,manifest,target=map(pathlib.Path,sys.argv[1:4])
expected=[]
for line in manifest.read_text().splitlines():
 fields=line.split()
 if len(fields)==2 and fields[1]=='singbox-v2.sh': expected.append(fields[0])
if len(expected)!=1 or expected[0]!=sys.argv[5] or not re.fullmatch('[a-f0-9]{64}',expected[0]) or hashlib.sha256(payload.read_bytes()).hexdigest()!=expected[0]:
 raise SystemExit('Manager SHA256 mismatch / 管理脚本 SHA256 校验失败，未覆盖文件')
def version(path):
 values=re.findall(r'^MANAGER_VERSION=([0-9]+\.[0-9]+\.[0-9]+)$',path.read_text(),re.M)
 if len(values)!=1: raise SystemExit('Manager version unknown / 无法识别管理脚本版本，未覆盖文件')
 return tuple(map(int,values[0].split('.')))
incoming=version(payload)
if incoming!=tuple(map(int,sys.argv[4].split('.'))):
 raise SystemExit('Installer/payload version mismatch / 安装入口与主脚本版本不一致')
if target.exists() and version(target)>incoming:
 raise SystemExit('Manager downgrade refused / 已安装版本较新，拒绝降级；请使用最新入口或 sb → f → 4')
PY_INSTALLER_VERIFY
}
install_manager() (
 local temp='' non_interactive=${SKYBYTE_NON_INTERACTIVE:-0}
 case $#:${1:-} in
  0:) ;;
  1:--non-interactive) non_interactive=1;;
  1:--help|1:-h) printf '%s\n' 'Usage: bash install.sh [--non-interactive]' 'Non-interactive installs the manager only; it does not install nodes or enter menus.';return 0;;
  *) err 'Unknown installer option / 安装参数无效';return 2;;
 esac
 [[ $non_interactive == 0 || $non_interactive == 1 ]] || { err 'SKYBYTE_NON_INTERACTIVE must be 0 or 1';return 2; }
 installer_root || return 1
 installer_guard && installer_dependencies || return 1
 exec 9>"$MANAGER_LOCK"
 flock -n 9 || { err 'Another management task is running / 其他管理任务正在运行';return 1; }
 mkdir -p "$MANAGER_DIR" || return 1
 temp=$(mktemp "$MANAGER_DIR/.install.XXXXXX") || return 1
 trap 'rm -f -- "$temp" "$temp.sha256"' EXIT
 curl -q -fsSL --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 60 --max-filesize 65536 "$RELEASE_URL/SHA256SUMS" -o "$temp.sha256" || return 1
 curl -q -fsSL --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 120 "$URL" -o "$temp" || return 1
 installer_verify "$temp" "$temp.sha256" || return 1
 if ! grep -q '^# SKYBYTE Manager V2.1 community manager;' "$temp" || ! bash -n "$temp";then err 'Invalid manager download / 下载的管理脚本无效';return 1;fi
 bash "$temp" --self-check >/dev/null || return 1
 installer_guard || return 1
 chmod 700 "$temp" && mv -f -- "$temp" "$MANAGER_TARGET" || return 1
 if [[ $non_interactive == 1 ]];then
  printf 'Manager installed: %s\nNo nodes were installed. Run: bash %s\n' "$MANAGER_TARGET" "$MANAGER_TARGET"
  return 0
 fi
 installer_launch
)
if [[ ${BASH_SOURCE[0]} == "$0" ]];then install_manager "$@";fi
