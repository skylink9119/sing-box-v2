#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
if [[ -t 2 && -z ${NO_COLOR:-} ]]; then RED=$'\033[1;31m'; RESET=$'\033[0m'; else RED=''; RESET=''; fi
err(){ printf '%s%s%s\n' "$RED" "$*" "$RESET" >&2; }
URL='https://raw.githubusercontent.com/skylink9119/sing-box-v2/main/singbox-v2.sh'
MANAGER_DIR=/usr/local/lib/singbox-v2
MANAGER_TARGET=$MANAGER_DIR/singbox-v2.sh
MANAGER_LOCK=/run/singbox-v2.lock
OS_RELEASE=${OS_RELEASE:-/etc/os-release}
APT_ROOT=${APT_ROOT:-/etc/apt}
L(){ printf '%s / %s' "$1" "$2"; }
warn(){ printf '%s\n' "$*" >&2; }
# @include packages.sh
installer_dependencies(){
 local name
 local missing=()
 for name in curl flock python3;do command -v "$name" >/dev/null || missing+=("$name");done
 if (( ${#missing[@]} ));then
  warn "Missing tools: ${missing[*]}; installing base dependencies / 缺少工具：${missing[*]}，正在自动安装基础依赖"
  apt_install curl ca-certificates python3 util-linux || return 1
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
install_manager() (
 installer_root || return 1
 local temp=''
 installer_guard && installer_dependencies || return 1
 exec 9>"$MANAGER_LOCK"
 flock -n 9 || { err 'Another management task is running / 其他管理任务正在运行';return 1; }
 mkdir -p "$MANAGER_DIR" || return 1
 temp=$(mktemp "$MANAGER_DIR/.install.XXXXXX") || return 1
 trap 'rm -f -- "$temp"' EXIT
 curl -q -fsSL --proto '=https' --proto-redir '=https' --retry 2 --connect-timeout 10 --max-time 120 "$URL" -o "$temp" || return 1
 if ! grep -q '^# SKYBYTE Manager V2.1 community manager;' "$temp" || ! bash -n "$temp";then err 'Invalid manager download / 下载的管理脚本无效';return 1;fi
 if command -v python3 >/dev/null;then bash "$temp" --self-check >/dev/null || return 1;fi
 installer_guard || return 1
 chmod 700 "$temp" && mv -f -- "$temp" "$MANAGER_TARGET" || return 1
 installer_launch
)
if [[ ${BASH_SOURCE[0]} == "$0" ]];then install_manager;fi
