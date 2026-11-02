# lib/lifecycle.sh — build-time module; assembled by scripts/build.py.
uninstall_manager(){
 need_root
 if [[ ! -f $META && -f $BASE/xhttp/state.json ]];then
  xhttp_command guard || return 1
  confirm "$(L '备份后卸载本项目的 XHTTP / Xray 与管理脚本？' 'Back up and remove the managed XHTTP/Xray and manager?')" || return 0
  xhttp_command purge --confirmed || return 1
  manager_shortcut_remove || return 1
  local manager_file
  for manager_file in "$MANAGER_BIN" "$MANAGER_LIB";do
   if [[ -f $manager_file && ! -L $manager_file ]] && grep -q '^# SKYBYTE Manager V2.1 community manager;' "$manager_file";then rm -f -- "$manager_file" || return 1;fi
  done
  say '已卸载；XHTTP 私密备份和未知文件保留。' 'Removed; private XHTTP backups and unknown files retained.'
  return 0
 fi
 xhttp_command guard || return 1
 certificate_guard && warp_guard && hop_guard && acme_guard && online_guard && haproxy_guard || return 1
 users_guard || return 1
 need_root
 check_owned || return 1
 argo_guard || return 1
 local unit snap file description managed_certs
 unit="$SYSTEMD_DIR/sing-box.service"
 # Metadata alone is insufficient: refuse to remove another service or a replacement binary symlink.
 if [[ ! -f $unit || -L $unit || -L $BIN || -L $CONF || -L $META ]] ||
    ! grep -Fxq 'Description=sing-box (managed by singbox-v2)' "$unit" ||
    ! grep -Fxq "ExecStart=$BIN run -c $CONF" "$unit"; then
  err "$(L '服务不属于本工具或已被修改，拒绝卸载' 'Service is not owned by this manager or has changed; refusing uninstall')"; return 1
 fi
 for file in singbox-v2-update.service singbox-v2-update.timer singbox-v2-hop.service; do
  case $file in
   singbox-v2-update.service) description='Description=sing-box v2 weekly update';;
   singbox-v2-update.timer) description='Description=sing-box v2 weekly update timer';;
   singbox-v2-hop.service) description='Description=singbox V2 HY2 IPv4 port hopping';;
  esac
  if [[ -e $SYSTEMD_DIR/$file || -L $SYSTEMD_DIR/$file ]]; then
   if [[ -L $SYSTEMD_DIR/$file ]] || ! grep -Fxq "$description" "$SYSTEMD_DIR/$file"; then
    err "$(L "附属服务 $file 已修改，拒绝卸载" "Auxiliary unit $file has changed; refusing uninstall")"; return 1
   fi
  fi
 done
 warn "$(L '卸载将停止所有节点，删除本工具的服务、二进制、节点配置及订阅文件。' 'Uninstall stops all nodes and removes managed services, binary, node config and subscription exports.')"
 say '先自动备份并保留备份；外部证书、UFW 规则、BBR 设置和 vnStat 均保留。' 'A backup is created and retained; external certificates, UFW rules, BBR settings and vnStat are kept.'
 confirm "$(L '确认卸载 SKYBYTE Manager 与托管 sing-box？' 'Uninstall SKYBYTE Manager and managed sing-box?')" || return 0
 managed_certs=$(python3 - "$META" "$CONF" <<'PY'
import json,sys,pathlib
s=json.load(open(sys.argv[1])); root=pathlib.Path(sys.argv[2]).parent
paths=s.get('managed_certificates',[])
# Legacy generated self-signed certificates have a known managed pathname and mode.
if 'managed_certificates' not in s and s.get('cert_mode')=='1' and s.get('cert_path')==str(root/'hy2-selfsigned.crt'):
 paths=[str(root/'hy2-selfsigned.crt'),str(root/'hy2-selfsigned.key')]
allowed={'hy2-selfsigned.crt','hy2-selfsigned.key','hy2-backup.crt','hy2-backup.key','hy2-added.crt','hy2-added.key'}
for value in paths:
 p=pathlib.Path(value)
 if p.parent==root and p.name in allowed: print(p)
PY
 ) || return 1
 snap=$(backup) || { err "$(L '备份失败，已取消卸载' 'Backup failed; uninstall cancelled')"; return 1; }
 if [[ -f $BASE/xhttp/state.json ]];then xhttp_command purge --confirmed || return 1;fi
 users_stop || return 1
 if [[ -f $BASE/users.json ]]; then users_engine ledger "$snap" && backup_engine reseal "$snap" || return 1; fi
 online_remove || return 1
 haproxy_engine purge >/dev/null || return 1
 acme_remove || return 1
 users_remove || return 1
 warp_remove || return 1
 if [[ -f $BASE/argo-state.json ]]; then argo_remove_internal || return 1; fi
 if [[ -f $SYSTEMD_DIR/singbox-v2-update.timer ]]; then systemctl disable --now singbox-v2-update.timer || return 1; fi
 if [[ -f $SYSTEMD_DIR/singbox-v2-update.service ]]; then systemctl stop singbox-v2-update.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/singbox-v2-hop.service ]]; then systemctl disable --now singbox-v2-hop.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/singbox-v2-hop.service ]] && grep -Fxq "ExecStart=/usr/sbin/nft -f $BASE/hop.nft" "$SYSTEMD_DIR/singbox-v2-hop.service" && command -v nft >/dev/null && nft list table ip singbox_v2_hop >/dev/null 2>&1; then nft delete table ip singbox_v2_hop || return 1; fi
 if [[ -f $SYSTEMD_DIR/skybyte-certificate.timer ]]; then systemctl disable --now skybyte-certificate.timer || return 1; fi
 if [[ -f $SYSTEMD_DIR/skybyte-certificate.service ]]; then systemctl stop skybyte-certificate.service || return 1; fi
 rm -f "$SYSTEMD_DIR/skybyte-certificate.timer" "$SYSTEMD_DIR/skybyte-certificate.service" "$BASE/certificate-status.json"
 systemctl disable --now sing-box.service || return 1
 # Remove explicit managed files only; never recursively delete user configuration directories.
 rm -f -- "$unit" "$SYSTEMD_DIR/singbox-v2-update.service" "$SYSTEMD_DIR/singbox-v2-update.timer" "$SYSTEMD_DIR/singbox-v2-hop.service" "$BIN" "$CONF"
 while IFS= read -r file; do if [[ -n $file ]]; then rm -f -- "$file"; fi; done <<<"$managed_certs"
 for file in state.json language.conf hop.nft hop-iptables.sh core-version.json warp-rules.json warp-rules.previous.json nodes.txt subscription-base64.txt v2rayn-nodes.txt v2rayn-subscription.txt shadowrocket-nodes.txt shadowrocket-subscription.txt shadowrocket-native-nodes.txt shadowrocket-native-subscription.txt sing-box-client.json sing-box-client-ipv6.json clash-verge.yaml outbounds.json mihomo-proxies.yaml subscription-notes.txt hy2-client-ca.pem hy2-client-ca.cer hy2-client-ca.mobileconfig; do rm -f -- "$BASE/$file"; done
 # Remove executable copies only when they are identifiable manager scripts.
 manager_shortcut_remove || return 1
 for file in "$MANAGER_BIN" "$MANAGER_LIB"; do
  if [[ -f $file && ! -L $file ]] && grep -q '^# SKYBYTE Manager V2.1 community manager;' "$file"; then rm -f -- "$file"; fi
 done
 systemctl daemon-reload || return 1
 ok "$(L '卸载完成；备份保存在：' 'Uninstalled; backup retained at: ')$snap"
 warn "$(L 'UFW 放行规则、BBR 设置和备份中的私钥仍保留，请按需要人工管理。' 'UFW allow rules, BBR settings and backup private keys remain; manage them as needed.')"
}
