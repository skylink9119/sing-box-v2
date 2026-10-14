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
  DEBIAN_FRONTEND=noninteractive apt-get install -y "$@" || return 1
 else return "$status";fi
)
