#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
if [[ -t 2 && -z ${NO_COLOR:-} ]]; then RED=$'\033[1;31m'; RESET=$'\033[0m'; else RED=''; RESET=''; fi
err(){ printf '%s%s%s\n' "$RED" "$*" "$RESET" >&2; }
RELEASE_VERSION=2.8.18
RELEASE_URL=https://github.com/skylink9119/sing-box-v2/releases/download/v$RELEASE_VERSION
URL=$RELEASE_URL/singbox-v2.sh
MANAGER_DIR=/usr/local/lib/singbox-v2
MANAGER_TARGET=$MANAGER_DIR/singbox-v2.sh
MANAGER_LOCK=/run/singbox-v2.lock
OS_RELEASE=${OS_RELEASE:-/etc/os-release}
APT_ROOT=${APT_ROOT:-/etc/apt}
L(){ printf '%s / %s' "$1" "$2"; }
warn(){ printf '%s\n' "$*" >&2; }
# APT compatibility helpers. Archive conversion only targets official Bullseye entries.
APT_ROOT=${APT_ROOT:-/etc/apt}
apt_archive_filter(){
 local format=$1 file=$2
 awk -v format="$format" '
 function official(uri) {return uri ~ /^https?:\/\/(deb|security|ftp)\.debian\.org\/debian(-security)?\/?$/}
 # Keep the existing transport: minimal Bullseye images may not yet have CA roots.
 # APT still verifies the signed Release and package hashes over either transport.
 function archived(uri) {sub(/\/\/(deb|security|ftp)\.debian\.org/,"//archive.debian.org",uri);return uri}
 function listline(line, code,tail,hash,prefix,rest,option,end,fields,count,i,url,suite) {
  hash=index(line,"#");code=hash?substr(line,1,hash-1):line;tail=hash?substr(line,hash):""
  if (code !~ /^[ \t]*deb(-src)?[ \t]+/) return line
  match(code,/^[ \t]*deb(-src)?[ \t]+/);prefix=substr(code,1,RLENGTH);rest=substr(code,RLENGTH+1);option=""
  if (substr(rest,1,1)=="[") {end=index(rest,"]");if(!end)return line;option=substr(rest,1,end);rest=substr(rest,end+1);sub(/^[ \t]+/,"",rest)}
  count=split(rest,fields,/[ \t]+/);url=fields[1];suite=fields[2]
  if (!official(url) || suite !~ /^bullseye(-security|-updates)?$/) return line
  if ((suite=="bullseye-security") != (url ~ /debian-security\/?$/)) return line
  if (option=="") option="[check-valid-until=no]"
  else if (option ~ /check-valid-until=/) sub(/check-valid-until=[^] \t]+/,"check-valid-until=no",option)
  else sub(/\]$/," check-valid-until=no]",option)
  sub(url,archived(url),rest);changed=1
  return prefix option " " rest tail
 }
 function stanza(record,parts,n,i,field,value,uris,suites,enabled,u,s,num,active,out,line,validity) {
  n=split(record,parts,"\n");uris="";suites="";enabled="";field=""
  for(i=1;i<=n;i++) {
   line=parts[i];if(line ~ /^[ \t]*#/)continue
   if(line ~ /^[A-Za-z-]+:/) {field=tolower(line);sub(/:.*/,"",field);value=line;sub(/^[^:]+:[ \t]*/,"",value)}
   else if(line ~ /^[ \t]+/) {value=line;sub(/^[ \t]+/,"",value)} else {field="";continue}
   if(field=="uris")uris=uris " " value
   if(field=="suites")suites=suites " " value
   if(field=="enabled")enabled=tolower(value)
  }
  if(enabled=="no" || uris=="" || suites=="")return record
  sub(/^ +/,"",uris);sub(/^ +/,"",suites)
  num=split(uris,u,/[ \t]+/);for(i=1;i<=num;i++)if(!official(u[i]) || (u[i] ~ /debian-security\/?$/) != (u[1] ~ /debian-security\/?$/))return record
  num=split(suites,s,/[ \t]+/);for(i=1;i<=num;i++)if(s[i] !~ /^bullseye(-security|-updates)?$/)return record
  for(i=1;i<=num;i++)if((s[i]=="bullseye-security") != (u[1] ~ /debian-security\/?$/))return record
  out="";field="";validity=0
  for(i=1;i<=n;i++) {
   line=parts[i]
   if(line ~ /^[A-Za-z-]+:/) {field=tolower(line);sub(/:.*/,"",field)}
   else if(line !~ /^[ \t]+/)field=""
   if(field=="uris")gsub(/\/\/(deb|security|ftp)\.debian\.org/,"//archive.debian.org",line)
   if(field=="check-valid-until") {if(line ~ /^[A-Za-z-]+:/)line="Check-Valid-Until: no";else continue;validity=1}
   out=out (out==""?"":"\n") line
  }
  if(!validity)out=out "\nCheck-Valid-Until: no"
  changed=1;return out
 }
 BEGIN {if(format=="sources"){RS="";ORS="\n\n"}}
 {if(format=="sources")print stanza($0);else print listline($0)}
 END {if(!changed)exit 10}
 ' "$file"
}
apt_prepare_archive() (
 local id version file format temp result backup_dir='' relative
 id=$(awk -F= '$1=="ID" {gsub(/"/,"",$2);print $2}' "$OS_RELEASE") || return 1
 version=$(awk -F= '$1=="VERSION_ID" {gsub(/"/,"",$2);print $2}' "$OS_RELEASE") || return 1
 [[ $id == debian && $version == 11 ]] || return 0
 [[ ! -L $APT_ROOT && ! -L $APT_ROOT/sources.list.d ]] || { err "$(L 'APT 源目录是符号链接，拒绝修改' 'APT source directory is a symlink; refusing changes')";return 1; }
 local files=()
 [[ ! -e $APT_ROOT/sources.list && ! -L $APT_ROOT/sources.list ]] || files+=("$APT_ROOT/sources.list")
 shopt -s nullglob
 files+=("$APT_ROOT"/sources.list.d/*.list "$APT_ROOT"/sources.list.d/*.sources)
 # Inspect every source path before changing any of them.
 for file in ${files[@]+"${files[@]}"};do
  [[ -f $file && ! -L $file ]] || { err "$(L 'APT 源文件异常，拒绝修改' 'Unsafe APT source file; refusing changes')";return 1; }
 done
 for file in ${files[@]+"${files[@]}"};do
  format=${file##*.}
  temp=$(mktemp "$file.skybyte.XXXXXX") || return 1
  cp -p -- "$file" "$temp" || { rm -f -- "$temp";return 1; }
  if apt_archive_filter "$format" "$file" > "$temp";then result=0;else result=$?;fi
  if [[ $result == 10 ]];then rm -f -- "$temp";continue;fi
  if [[ $result != 0 ]];then rm -f -- "$temp";return "$result";fi
  if [[ -z $backup_dir ]];then
   backup_dir=$(mktemp -d "$APT_ROOT/skybyte-source-backup.XXXXXX") || { rm -f -- "$temp";return 1; }
   chmod 700 "$backup_dir" || return 1
  fi
  if [[ $file == "$APT_ROOT/sources.list" ]];then relative=sources.list;else relative="parts/${file##*/}";fi
  if ! mkdir -p "$backup_dir/$(dirname "$relative")" || ! cp -p -- "$file" "$backup_dir/$relative";then rm -f -- "$temp";return 1;fi
  if ! mv -f -- "$temp" "$file";then rm -f -- "$temp";return 1;fi
 done
 if [[ -n $backup_dir ]];then
  warn "$(L 'Debian 11 官方源已迁至归档；原文件已备份：' 'Official Debian 11 sources moved to archive; originals backed up: ')$backup_dir"
  warn "$(L '归档不提供新的官方安全更新；请规划升级系统。' 'The archive supplies no new official security updates; plan an OS upgrade.')"
 fi
)
apt_refresh(){
 apt_prepare_archive || return 1
 if ! apt-get -o APT::Update::Error-Mode=any -o Acquire::Retries=2 --allow-releaseinfo-change-suite update;then
  err "$(L '软件源索引更新失败，已停止安装；请检查上面的 DNS、签名或源地址错误。' 'Repository index refresh failed; installation stopped. Check DNS, signatures and source URLs above.')"
  return 1
 fi
}
apt_install() (
 local log status
 apt_refresh || return 1
 log=$(mktemp "${TMPDIR:-/tmp}/skybyte-apt.XXXXXX") || return 1
 trap 'rm -f -- "$log"' EXIT
 if DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" > "$log" 2>&1;then cat "$log";return 0;else status=$?;fi
 cat "$log"
 if grep -Eq '404[[:space:]]|404[[:space:]]+Not Found|Failed to fetch' "$log";then
  warn "$(L '安装包下载失败，刷新索引并重试一次。' 'Package download failed; refreshing indexes and retrying once.')"
  apt_refresh || return 1
  # Some archive CDN edges cache an earlier 404 even while the package exists.
  DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" -o Acquire::http::No-Cache=true -o Acquire::https::No-Cache=true || return 1
 else return "$status";fi
)
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
installer_verify(){
 python3 - "$1" "$2" "$MANAGER_TARGET" "$RELEASE_VERSION" <<'PY_INSTALLER_VERIFY'
import hashlib,pathlib,re,sys
payload,manifest,target=map(pathlib.Path,sys.argv[1:4])
expected=[]
for line in manifest.read_text().splitlines():
 fields=line.split()
 if len(fields)==2 and fields[1]=='singbox-v2.sh': expected.append(fields[0])
if len(expected)!=1 or not re.fullmatch('[a-f0-9]{64}',expected[0]) or hashlib.sha256(payload.read_bytes()).hexdigest()!=expected[0]:
 raise SystemExit('Manager SHA256 mismatch / 管理脚本 SHA256 校验失败，未覆盖文件')
def version(path):
 values=re.findall(r'^MANAGER_VERSION=([0-9]+\.[0-9]+\.[0-9]+)$',path.read_text(),re.M)
 if len(values)!=1: raise SystemExit('Manager version unknown / 无法识别管理脚本版本，未覆盖文件')
 return tuple(map(int,values[0].split('.')))
incoming=version(payload)
if incoming!=tuple(map(int,sys.argv[4].split('.'))):
 raise SystemExit('Installer/payload version mismatch / 安装入口与主脚本版本不一致')
if target.exists() and version(target)>incoming:
 raise SystemExit('Manager downgrade refused / 已安装版本较新，拒绝降级；请使用最新入口或 sb → e → 4')
PY_INSTALLER_VERIFY
}
install_manager() (
 installer_root || return 1
 local temp=''
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
 if command -v python3 >/dev/null;then bash "$temp" --self-check >/dev/null || return 1;fi
 installer_guard || return 1
 chmod 700 "$temp" && mv -f -- "$temp" "$MANAGER_TARGET" || return 1
 installer_launch
)
if [[ ${BASH_SOURCE[0]} == "$0" ]];then install_manager;fi
