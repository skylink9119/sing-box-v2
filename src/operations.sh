# Manager updates affect script copies, never node credentials or configurations.
manager_latest(){
 local target=$1
 curl -fsSL --retry 2 --connect-timeout 10 --max-time 30 https://api.github.com/repos/skylink9119/sing-box-v2/releases/latest -o "$target" || return 1
 python3 - "$target" <<'PY'
import json,re,sys
r=json.load(open(sys.argv[1]));tag=r['tag_name']
assert not r.get('draft') and not r.get('prerelease') and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+',tag)
a=next(a for a in r['assets'] if a['name']=='singbox-v2.sh')
assert re.fullmatch(r'sha256:[a-fA-F0-9]{64}',a.get('digest',''))
print(tag[1:])
PY
}
manager_update_apply(){
 local candidate=$1 version=$2 snapshot=$3 path active=false tunnel=false rc=0 stage
 local -a targets=("$MANAGER_LIB")
 for path in "$MANAGER_LIB" "$MANAGER_BIN"; do
  [[ ! -L $path ]] || { err "$(L '管理脚本是符号链接，拒绝覆盖' 'Refusing manager symlink')"; return 1; }
  if [[ -e $path ]]; then
   grep -q '^# SKYBYTE Manager V2.1 community manager;' "$path" || { err "$(L '管理脚本归属异常' 'Manager ownership mismatch')"; return 1; }
   if [[ $path != "$MANAGER_LIB" ]]; then targets+=("$path"); fi
  fi
 done
 bash -n "$candidate" && [[ $(bash "$candidate" --self-check) == "$version" ]] || return 1
 users_guard && argo_guard || return 1
 mkdir -m 700 "$snapshot" || return 1
 for path in "${targets[@]}"; do
  if [[ -f $path ]]; then cp -p "$path" "$snapshot/$(basename "$path")" || return 1; fi
 done
 if [[ -f $BASE/users.json ]] && systemctl is-active --quiet skybyte-users.service; then active=true; users_stop || return 1; fi
 if [[ -f $BASE/argo-state.json ]] && systemctl is-active --quiet skybyte-argo-tunnel.service; then tunnel=true; systemctl stop skybyte-argo-tunnel.service || { [[ $active != true ]] || users_start; return 1; }; fi
 for path in "${targets[@]}"; do
  mkdir -p "$(dirname "$path")" || { rc=1; break; }
  # Rename within the target filesystem, including when the running script is replaced.
  stage=$(mktemp "$path.stage.XXXXXX") || { rc=1; break; }
  if ! command install -m 700 "$candidate" "$stage" || ! mv -f "$stage" "$path"; then rm -f "$stage"; rc=1; break; fi
 done
 if [[ $rc == 0 && $active == true ]]; then systemctl start skybyte-users.service && systemctl is-active --quiet skybyte-users.service || rc=1; fi
 if [[ $rc == 0 && $tunnel == true ]]; then systemctl start skybyte-argo-tunnel.service && systemctl is-active --quiet skybyte-argo-tunnel.service || rc=1; fi
 if [[ $rc != 0 ]]; then
  [[ $active != true ]] || systemctl stop skybyte-users.service || :
  [[ $tunnel != true ]] || systemctl stop skybyte-argo-tunnel.service || :
  for path in "${targets[@]}"; do
   if [[ -f $snapshot/$(basename "$path") ]]; then command install -m 700 "$snapshot/$(basename "$path")" "$path" || return 1; else rm -f "$path"; fi
  done
  [[ $active != true ]] || systemctl start skybyte-users.service || :
  [[ $tunnel != true ]] || systemctl start skybyte-argo-tunnel.service || :
  err "$(L '管理脚本更新失败，已回滚脚本' 'Manager update failed; script copies rolled back')"; return 1
 fi
 ok "$(L '管理脚本更新完成：' 'Manager updated: ')v$version"
 say "脚本备份：$snapshot" "Script backup: $snapshot"
}
manager_update(){
 local tmp version digest snapshot rc
 require_cmd curl && require_cmd python3 || return 1
 tmp=$(mktemp -d "$BASE/manager-update.XXXXXX") || return 1
 version=$(manager_latest "$tmp/release.json") || { rm -rf "$tmp"; return 1; }
 say "管理脚本：v$MANAGER_VERSION → v$version" "Manager: v$MANAGER_VERSION → v$version"
 if [[ $MANAGER_VERSION == "$version" ]]; then rm -rf "$tmp"; ok "$(L '已是最新发布版' 'Already on the latest release')"; return 0; fi
 if ! python3 - "$MANAGER_VERSION" "$version" <<'PY'
import sys
sys.exit(0 if tuple(map(int,sys.argv[2].split('.')))>tuple(map(int,sys.argv[1].split('.'))) else 1)
PY
 then rm -rf "$tmp"; warn "$(L '当前版本更新，不自动降级' 'Current version is newer; refusing downgrade')"; return 0; fi
 confirm "$(L '更新管理脚本？受限用户和 Argo 隧道会短暂重启。' 'Update manager? Quota users and Argo tunnel briefly restart.')" || { rm -rf "$tmp"; return 0; }
 digest=$(python3 - "$tmp/release.json" <<'PY'
import json,sys
print(next(a['digest'][7:] for a in json.load(open(sys.argv[1]))['assets'] if a['name']=='singbox-v2.sh'))
PY
 ) || { rm -rf "$tmp"; return 1; }
 if ! curl -fsSL --retry 2 --max-time 120 "https://github.com/skylink9119/sing-box-v2/releases/download/v$version/singbox-v2.sh" -o "$tmp/candidate" ||
    ! python3 - "$tmp/candidate" "$digest" <<'PY'
import hashlib,sys
sys.exit(0 if hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()==sys.argv[2].lower() else 1)
PY
 then rm -rf "$tmp"; err "$(L '下载或 SHA256 验证失败' 'Download or SHA256 verification failed')"; return 1; fi
 mkdir -p "$BASE/manager-backups"
 snapshot="$BASE/manager-backups/$(date +%Y%m%d-%H%M%S)-$RANDOM"
 rc=0; manager_update_apply "$tmp/candidate" "$version" "$snapshot" || rc=$?
 rm -rf "$tmp"; return "$rc"
}
users_summary(){
 if [[ -f $BASE/users.json ]]; then
  users_engine summary || warn "$(L '用户数据异常，请进入用户诊断' 'Invalid user data; open diagnostics')"
  startup_service_info "$(L '用户配额服务' 'User quota supervisor')" true skybyte-users.service
 else say '用户管理：尚未初始化' 'User management: not initialized'; fi
}
users_diagnostics(){
 users_guard || return 1
 users_engine diagnose "${1:-}"
 say '恢复步骤：修复配置/端口冲突后，选择启用用户；服务未启动时选择启动用户服务。' 'Recovery: fix config/port conflicts, then enable the account; start the supervisor if inactive.'
 say '日志可能含节点地址，请在本机检查，不要公开完整日志。' 'Logs may contain node addresses; inspect locally and avoid publishing full logs.'
 systemctl --no-pager status skybyte-users.service || :
}
resource_info(){
 require_cmd ps || { say '请安装 procps 后重试' 'Install procps and retry'; return 1; }
 python3 - "$BASE" "$BIN" "${LANGUAGE_CHOICE:-zh_CN}" <<'PY'
import pathlib,subprocess,sys
base=pathlib.Path(sys.argv[1]);binary=sys.argv[2]
r=subprocess.run(['ps','-eo','pid=,rss=,args='],capture_output=True,text=True,check=True)
cores=users=total=user_rss=0
for line in r.stdout.splitlines():
 parts=line.split(None,2)
 if len(parts)!=3:continue
 pid,rss,args=parts
 if not args.startswith(binary+' run -c '):continue
 cores+=1;total+=int(rss)
 if args[len(binary+' run -c '):].startswith(str(base/'users')+'/'):
  users+=1;user_rss+=int(rss)
en=sys.argv[3]=='en_US'
print(('sing-box processes / RSS: ' if en else 'sing-box 进程数 / RSS：')+f'{cores} / {total/1024:.1f} MiB')
print(('Quota user processes / RSS: ' if en else '受限用户进程数 / RSS：')+f'{users} / {user_rss/1024:.1f} MiB')
p=pathlib.Path('/proc/meminfo')
if p.exists():
 m={line.split(':')[0]:int(line.split()[1]) for line in p.read_text().splitlines() if line.split()[1].isdigit()}
 print(('System available / total RAM: ' if en else '系统可用 / 总内存：')+f"{m.get('MemAvailable',0)/1024:.1f} / {m['MemTotal']/1024:.1f} MiB")
p=pathlib.Path('/proc/loadavg')
if p.exists():print(('Load (1/5/15 min): ' if en else '负载（1/5/15 分钟）：')+' '.join(p.read_text().split()[:3]))
print('RSS includes shared memory; this is a snapshot, not a capacity guarantee.' if en else 'RSS 含共享内存；这是当前快照，不能保证最大承载人数。')
PY
}
certificate_info(){
 [[ -f $CONF ]] || return 0
 require_cmd openssl || return 1
 python3 - "$CONF" "${LANGUAGE_CHOICE:-zh_CN}" <<'PY'
import datetime,json,ssl,subprocess,sys
cfg=json.load(open(sys.argv[1]));en=sys.argv[2]=='en_US'
for inbound in cfg.get('inbounds',[]):
 if inbound['type']!='hysteria2':continue
 path=inbound['tls']['certificate_path']
 r=subprocess.run(['openssl','x509','-in',path,'-noout','-enddate'],capture_output=True,text=True)
 if r.returncode:
  print('HY2 certificate unreadable' if en else 'HY2 证书无法读取');continue
 expiry=ssl.cert_time_to_seconds(r.stdout.strip().split('=',1)[1])
 days=int((expiry-datetime.datetime.now(datetime.timezone.utc).timestamp())//86400)
 print(('HY2 certificate days remaining: ' if en else 'HY2 证书剩余天数：')+str(days))
 if days<=30:print('WARNING: expired or expires within 30 days; renew and reload.' if en else '警告：证书已过期或将在 30 天内到期，请续签并重载。')
PY
}
certificate_guard(){
 local unit expected
 for unit in skybyte-certificate.service skybyte-certificate.timer; do
  expected='Description=SKYBYTE managed certificate monitor'
  if [[ -e $SYSTEMD_DIR/$unit || -L $SYSTEMD_DIR/$unit ]]; then
   if [[ -L $SYSTEMD_DIR/$unit ]] || ! grep -Fxq "$expected" "$SYSTEMD_DIR/$unit"; then err "$(L '证书服务归属异常' 'Certificate unit ownership mismatch')"; return 1; fi
   if [[ $unit == *.service ]]; then grep -Fxq "ExecStart=/bin/bash $MANAGER_BIN --certificate-check" "$SYSTEMD_DIR/$unit" || return 1; fi
  fi
 done
 [[ ! -L $BASE/certificate-status.json ]] || return 1
}
certificate_identity(){
 python3 - "$CONF" <<'PY'
import json,sys
for i in json.load(open(sys.argv[1]))['inbounds']:
 if i['type']=='hysteria2':
  t=i['tls'];print(t['certificate_path']);print(t['key_path']);print(t['server_name']);break
else:sys.exit(1)
PY
}
certificate_record(){
 python3 - "$BASE/certificate-status.json" "$1" <<'PY'
import json,os,pathlib,sys,tempfile
p=pathlib.Path(sys.argv[1]);assert not p.is_symlink()
fd,tmp=tempfile.mkstemp(dir=p.parent)
with os.fdopen(fd,'w') as f:json.dump({'fingerprint':sys.argv[2]},f);f.flush();os.fsync(f.fileno())
os.replace(tmp,p)
PY
}
certificate_reload(){
 check_owned && certificate_guard && users_guard || return 1
 local identity cert key name fingerprint snap active=false admin=false
 identity=$(certificate_identity) || return 1
 { IFS= read -r cert; IFS= read -r key; IFS= read -r name; } <<<"$identity"
 validate_certificate "$cert" "$key" "$name" && "$BIN" check -c "$CONF" || return 1
 fingerprint=$(openssl x509 -in "$cert" -noout -fingerprint -sha256) || return 1
 snap=$(backup) || return 1
 if systemctl is-active --quiet sing-box.service; then admin=true; fi
 if [[ -f $BASE/users.json ]] && systemctl is-active --quiet skybyte-users.service; then active=true; users_stop || return 1; fi
 if [[ -f $BASE/users.json ]]; then
  if ! users_engine certificates || ! users_engine validate "$BIN"; then users_restore_snapshot "$snap" || :; [[ $active == true ]] || users_stop || :; return 1; fi
 fi
 if { [[ $admin == true ]] && ! { systemctl restart sing-box.service && service_healthy; }; } ||
    { [[ $active == true ]] && ! { systemctl start skybyte-users.service && systemctl is-active --quiet skybyte-users.service; }; }; then
  [[ $active != true ]] || users_stop || :
  users_restore_snapshot "$snap" || :
  [[ $active == true ]] || users_stop || :
  err "$(L '重载失败，已尝试恢复用户证书；请检查主服务' 'Reload failed; attempted user certificate rollback; inspect main service')"; return 1
 fi
 exports >/dev/null || return 1
 if [[ -f $BASE/users.json ]]; then users_engine export_all | while IFS= read -r id; do users_export "$id" >/dev/null || return 1; done; fi
 certificate_record "$fingerprint" || return 1
 ok "$(L '证书已同步并重载原先运行的 HY2 服务' 'Certificate synchronized; previously running HY2 services reloaded')"
 warn "$(L '自签名证书更换后，客户端须重新核实并导入信任。' 'If a self-signed certificate changed, verify and re-import client trust.')"
}
certificate_check(){
 check_owned && certificate_guard || return 1
 certificate_info
 local identity cert key name fingerprint previous
 identity=$(certificate_identity) || return 0
 { IFS= read -r cert; IFS= read -r key; IFS= read -r name; } <<<"$identity"
 validate_certificate "$cert" "$key" "$name" || return 1
 fingerprint=$(openssl x509 -in "$cert" -noout -fingerprint -sha256) || return 1
 if [[ ! -f $BASE/certificate-status.json ]]; then certificate_record "$fingerprint"; return; fi
 previous=$(python3 - "$BASE/certificate-status.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['fingerprint'])
PY
 ) || return 1
 [[ $fingerprint != "$previous" ]] || return 0
 if [[ $(state cert_mode) == 2 ]]; then certificate_reload; else warn "$(L '自签名证书已变化，请手动重载并更新客户端信任' 'Self-signed certificate changed; reload manually and update client trust')"; fi
}
certificate_menu(){
 check_owned && certificate_guard || return 1
 certificate_identity >/dev/null || { err "$(L '未安装 HY2' 'HY2 not installed')"; return 1; }
 local choice
 say '1 查看证书有效期  2 续签后同步并重载  3 开启每日检查  4 关闭每日检查  0 返回' '1 Expiry  2 Reload renewed certificate  3 Enable daily checks  4 Disable daily checks  0 Back'
 read -r -p '> ' choice || return 0
 case $choice in
  1) certificate_info;;
  2) confirm "$(L '同步证书并重启正在运行的 HY2 服务？' 'Sync certificates and restart active HY2 services?')" && certificate_reload;;
  3)
   users_guard setup || return 1
   certificate_check || return 1
   if [[ ! $SCRIPT_PATH -ef $MANAGER_BIN ]]; then command install -m 700 "$SCRIPT_PATH" "$MANAGER_BIN" || return 1; fi
   cat >"$SYSTEMD_DIR/skybyte-certificate.service" <<UNIT
[Unit]
Description=SKYBYTE managed certificate monitor
[Service]
Type=oneshot
ExecStart=/bin/bash $MANAGER_BIN --certificate-check
UMask=0077
UNIT
   cat >"$SYSTEMD_DIR/skybyte-certificate.timer" <<'UNIT'
[Unit]
Description=SKYBYTE managed certificate monitor
[Timer]
OnCalendar=daily
RandomizedDelaySec=15m
Persistent=true
[Install]
WantedBy=timers.target
UNIT
   systemctl daemon-reload && systemctl enable --now skybyte-certificate.timer
   say '检查不会申请证书。域名证书有效续签后会自动同步；可在续签工具中设置 --certificate-reload 钩子。' 'Checks do not issue certificates. Valid renewed domain certificates are synchronized; renewal tools can call --certificate-reload.';;
  4) if [[ -f $SYSTEMD_DIR/skybyte-certificate.timer ]]; then systemctl disable --now skybyte-certificate.timer; fi;;
  0) return 0;; *) return 1;;
 esac
}

