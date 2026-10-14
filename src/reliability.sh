installation_commit(){
 python3 - "$@" <<'PY_INSTALL_COMMIT'
import json,os,pathlib,shutil,sys
stage,exe,conf,meta,base=map(pathlib.Path,sys.argv[1:]);cfg=json.loads((stage/'config/config.json').read_text());s=json.loads((stage/'state.json').read_text())
pairs=[(stage/'sing-box',exe,0o755)]
if s['cert_mode']=='1':
 for i in cfg['inbounds']:
  if i['type']=='hysteria2':
   for field in ('certificate_path','key_path'):
    src=pathlib.Path(i['tls'][field]);dest=conf.parent/src.name;pairs.append((src,dest,0o600));i['tls'][field]=str(dest)
   s['cert_path']=i['tls']['certificate_path'];s['managed_certificates']=[i['tls']['certificate_path'],i['tls']['key_path']]
(stage/'config/config.json').write_text(json.dumps(cfg,indent=2));(stage/'state.json').write_text(json.dumps(s,indent=2))
pairs.extend([(stage/'config/config.json',conf,0o600),(stage/'state.json',meta,0o600)])
for name in ('nodes.txt','subscription-base64.txt','v2rayn-nodes.txt','v2rayn-subscription.txt','shadowrocket-nodes.txt','shadowrocket-subscription.txt','shadowrocket-native-nodes.txt','shadowrocket-native-subscription.txt','sing-box-client.json','clash-verge.yaml','outbounds.json','mihomo-proxies.yaml','subscription-notes.txt','hy2-client-ca.pem','hy2-client-ca.cer','hy2-client-ca.mobileconfig'):
 if (stage/name).exists():pairs.append((stage/name,base/name,0o600))
created=[];journal=stage/'created.json';journal.write_text('[]')
for src,dest,mode in pairs:
 dest.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(dest,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
 created.append(str(dest));journal.write_text(json.dumps(created))
 with os.fdopen(fd,'wb') as f:f.write(src.read_bytes());f.flush();os.fsync(f.fileno())
PY_INSTALL_COMMIT
}
installation_cleanup(){
 [[ -n ${stage:-} && -d $stage ]] || return 0
 if [[ ${committed:-false} != true ]]; then
  if [[ -f $stage/created.json ]]; then
   if [[ -f $SYSTEMD_DIR/sing-box.service ]] && grep -Fxq "ExecStart=$final_bin run -c $final_conf" "$SYSTEMD_DIR/sing-box.service"; then
    systemctl disable --now sing-box.service >/dev/null 2>&1 || :;rm -f "$SYSTEMD_DIR/sing-box.service";systemctl daemon-reload >/dev/null 2>&1 || :
   fi
   python3 - "$stage/created.json" <<'PY_INSTALL_CLEAN'
import json,pathlib,sys
for name in json.load(open(sys.argv[1])):
 p=pathlib.Path(name)
 if p.is_file() and not p.is_symlink():p.unlink()
PY_INSTALL_CLEAN

  fi
 fi
 rm -rf "$stage"
}
core_versions(){
 check_owned || return 1
 local choice version current
 current=$("$BIN" version | awk 'NR==1{print $3}') || return 1
 say "当前内核：${current}；本版测试内核：$CORE_RECOMMENDED" "Current core: $current; tested core for this release: $CORE_RECOMMENDED"
 prompt_options '1 安装本版测试内核  2 最新稳定版  3 指定版本 / 降级  0 返回' '1 Tested core  2 Latest stable  3 Specific version / downgrade  0 Back'
 prompt_read '> ' choice || return 0
 case $choice in 1) version=$CORE_RECOMMENDED;; 2) version=$(latest) || return 1;; 3) prompt_read "$(L '版本号（例如 1.14.3）：' 'Version (e.g. 1.14.3): ')" version || return 0;; 0) return 0;; *) return 1;; esac
 [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
 [[ $version != "$current" ]] || { ok "$(L '已是所选版本' 'Already on selected version')"; return 0; }
 say '候选内核必须能检查全部托管配置；不自动重写配置。降级可能不兼容。' 'Candidate core must validate every managed config; configs are not rewritten. Downgrades may be incompatible.'
 confirm "$(L "切换内核 $current → ${version}？" "Switch core $current → $version?")" && apply_update "$version"
}
backup_engine(){
 python3 - "$BASE" "$BACKUP" "$CONF" "$BIN" "$@" <<'PY_BACKUP'
# @include backup.py
PY_BACKUP
}
backup_tools(){
 check_owned || return 1
 local choice path output keep pass tmp
 prompt_options '1 备份列表  2 新建备份  3 恢复预检  4 加密导出  5 导入加密备份  6 保留数量 / 清理  0 返回' '1 List  2 Create  3 Restore preflight  4 Encrypted export  5 Import encrypted backup  6 Retention cleanup  0 Back'
 prompt_read '> ' choice || return 0
 case $choice in
  1) backup_engine list;; 2) backup;;
  3) prompt_read "$(L '备份目录：' 'Backup directory: ')" path || return 0;backup_engine preflight "$path";;
  4)
   prompt_read "$(L '备份目录：' 'Backup directory: ')" path || return 0
   backup_engine preflight "$path" || return 1
   prompt_read "$(L '新导出文件绝对路径（.gpg）：' 'New absolute export path (.gpg): ')" output || return 0
   [[ $output == /* && ! -e $output && ! -L $output ]] || return 1
   command -v gpg >/dev/null || { apt_install gnupg || return 1; }
   prompt_read "$(L '加密口令（隐藏，至少12字符）：' 'Encryption passphrase (hidden, minimum 12 characters): ')" pass secret || return 0;echo
   [[ ${#pass} -ge 12 ]] || return 1
   tmp=$(mktemp "$BASE/archive.XXXXXX") || return 1
   backup_engine archive "$path" "$tmp" || { rm -f "$tmp";return 1; }
   if ! gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 --no-symkey-cache --symmetric --cipher-algo AES256 --output "$tmp.gpg" "$tmp" 3< <(printf '%s\n' "$pass"); then rm -f "$tmp" "$tmp.gpg";return 1;fi
   unset pass
   python3 - "$tmp.gpg" "$output" <<'PY_GPG_EXPORT' || { rm -f "$tmp" "$tmp.gpg";return 1; }
import os,pathlib,sys
fd=os.open(sys.argv[2],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'wb') as f:f.write(pathlib.Path(sys.argv[1]).read_bytes());f.flush();os.fsync(f.fileno())
PY_GPG_EXPORT
   local rc=$?;rm -f "$tmp" "$tmp.gpg";[[ $rc == 0 ]] || return "$rc";ok "$(L '加密备份已导出' 'Encrypted backup exported')";;
  5)
   prompt_read "$(L '加密备份文件：' 'Encrypted backup file: ')" path || return 0
   [[ -f $path && ! -L $path ]] || return 1;require_cmd gpg || return 1
   prompt_read "$(L '解密口令（隐藏）：' 'Decryption passphrase (hidden): ')" pass secret || return 0;echo
   tmp=$(mktemp "$BASE/archive.XXXXXX") || return 1
   if ! gpg --batch --yes --pinentry-mode loopback --passphrase-fd 3 --no-symkey-cache --decrypt --output "$tmp" "$path" 3< <(printf '%s\n' "$pass");then rm -f "$tmp";return 1;fi
   unset pass;local rc=0;backup_engine import "$tmp" || rc=$?;rm -f "$tmp";return "$rc";;
  6) prompt_read "$(L '保留最新备份数量 [10]：' 'Keep newest backups [10]: ')" keep || return 0;keep=${keep:-10}
   backup_engine prune "$keep" preview || return 1
   confirm "$(L '删除上述旧托管备份？' 'Delete the listed older managed backups?')" && backup_engine prune "$keep" apply;;
  0) return 0;; *) return 1;;
 esac
}
