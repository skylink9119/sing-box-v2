# lib/backup.sh — build-time module; assembled by scripts/build.py.
backup(){
 check_owned || return 1
 local path file
 users_guard && warp_guard && acme_guard && online_guard && haproxy_guard || return 1
 path="$BACKUP/$(date +%Y%m%d-%H%M%S)-$RANDOM"
 mkdir -m 700 "$path" "$path/config" || return 1
 cp "$CONF" "$path/config/config.json" || return 1
 cp "$META" "$path/state.json" || return 1
 cp "$BIN" "$path/sing-box.bin" || return 1
 if [[ -f "$BASE/hop.nft" ]]; then cp "$BASE/hop.nft" "$path/hop.nft" || return 1; fi
 for file in argo-state.json argo-server.json argo-empty.yml argo.token warp-state.json warp-gateway.json warp-client.json warp-rules.json warp-rules.previous.json core-version.json hop-iptables.sh; do
  if [[ -f $BASE/$file ]]; then cp "$BASE/$file" "$path/$file" || return 1; fi
 done
 if [[ -f $SYSTEMD_DIR/skybyte-warp-gateway.service ]]; then
  cp "$SYSTEMD_DIR/skybyte-warp-gateway.service" "$path/warp-gateway.unit" || return 1
  if systemctl is-active --quiet skybyte-warp-gateway.service; then echo true > "$path/warp-gateway-active"; else echo false > "$path/warp-gateway-active"; fi
 fi
 if [[ -f $BASE/argo-state.json && -f $BASE/cloudflared ]]; then cp "$BASE/cloudflared" "$path/cloudflared.bin" || return 1; fi
 python3 - "$path" "$CONF" <<'PY' || return 1
import json,sys,shutil,pathlib
root=pathlib.Path(sys.argv[1]); cfg=json.load(open(sys.argv[2])); meta=json.load(open(root/'state.json'))
for i in cfg['inbounds']:
 if i['type']=='hysteria2':
  for field,name in [('certificate_path','hy2-backup.crt'),('key_path','hy2-backup.key')]:
   shutil.copyfile(i['tls'][field],root/'config'/name)
   i['tls'][field]=str(pathlib.Path(sys.argv[2]).parent/name)
  meta['cert_path']=i['tls']['certificate_path']
  meta['managed_certificates']=[i['tls']['certificate_path'],i['tls']['key_path']]
(root/'config'/'config.json').write_text(json.dumps(cfg,indent=2))
(root/'state.json').write_text(json.dumps(meta,indent=2))
PY
 if [[ -f $BASE/users.json ]]; then users_engine backup "$path" || return 1; fi
 if [[ -f $BASE/acme-state.json ]];then cp "$BASE/acme-state.json" "$path/acme-state.json" || return 1;fi
 if [[ -d $BASE/acme ]];then cp -aL "$BASE/acme" "$path/acme" || return 1;fi
 if [[ -f $BASE/subscriptions.json ]];then
  python3 - "$BASE/subscriptions.json" "$path" "$BASE" <<'PY_SUB_BACKUP' || return 1
import json,pathlib,shutil,sys
s=json.load(open(sys.argv[1]));root=pathlib.Path(sys.argv[2]);base=pathlib.Path(sys.argv[3])
for field,name in [('cert','subscription-backup.crt'),('key','subscription-backup.key')]:
 shutil.copyfile(s[field],root/name);(root/name).chmod(0o600);s[field]=str(base/name)
(root/'subscriptions.json').write_text(json.dumps(s,indent=2));(root/'subscriptions.json').chmod(0o600)
PY_SUB_BACKUP
  if [[ -f $SYSTEMD_DIR/skybyte-subscriptions.service ]];then cp "$SYSTEMD_DIR/skybyte-subscriptions.service" "$path/subscriptions.unit" || return 1;fi
  if systemctl is-active --quiet skybyte-subscriptions.service;then echo true > "$path/subscriptions.active";else echo false > "$path/subscriptions.active";fi
 fi
 if [[ -d $BASE/haproxy ]];then haproxy_engine backup "$path/haproxy" >/dev/null || return 1;fi
 if [[ -f $BASE/xhttp/state.json ]];then xhttp_command backup "$path/xhttp.tar.gz" || return 1;fi
 backup_engine manifest "$path" || return 1
 chmod -R go-rwx "$path" || return 1; printf '%s\n' "$path"
}
restore() (
 check_owned || return 1
 local path snap='' restore_stage='' restore_started=false restore_done=false service active enabled
 trap restore_cleanup EXIT
 find "$BACKUP" -mindepth 1 -maxdepth 1 -type d | sort -r
 prompt_read "$(L '完整备份路径：' 'Full backup directory path: ')" path || return
 path=$(realpath "$path") || return 1
 [[ $path == "$(realpath "$BACKUP")/"* && -f $path/config/config.json && -f $path/sing-box.bin && -f $path/state.json ]] || { err "$(L '备份路径错误' 'Invalid backup path')"; return 1; }
 confirm "$(L '恢复配置并重启？' 'Restore configuration and restart?')" || return 0
 configuration_guard && argo_guard && hop_guard || return 1
 users_guard || return 1
 backup_engine preflight "$path" || return 1
 haproxy_engine check_configs "$path" || return 1
 snap=$(backup) || return 1
 restore_stage=$(mktemp -d "$BASE/restore.XXXXXX") || return 1
 backup_engine restore_plan "$path" "$restore_stage" || return 1
 for service in skybyte-warp-gateway.service sing-box.service skybyte-argo-node.service skybyte-argo-tunnel.service skybyte-users.service singbox-v2-hop.service;do
  [[ -f $SYSTEMD_DIR/$service ]] || continue
  active=false;enabled=false
  if systemctl is-active --quiet "$service";then active=true;fi
  if systemctl is-enabled --quiet "$service";then enabled=true;fi
  printf '%s %s %s\n' "$service" "$active" "$enabled" >> "$restore_stage/services"
 done
 restore_started=true
 users_stop || return 1
 backup_engine restore_apply "$restore_stage" || return 1
 "$BIN" check -c "$CONF" && warp_restore_snapshot "$path" && admin_restart && argo_restore_snapshot "$path" && users_restore_snapshot "$path" || return 1
 # Hopping is host state: avoid restoring metadata claiming rules that are absent.
 hop_disable || return 1
 exports >/dev/null || return 1
 if [[ -f $BASE/users.json ]];then users_engine export_all | while IFS= read -r service;do users_export "$service" >/dev/null || return 1;done || return 1;fi
 auxiliary_restore_snapshot "$path" || return 1
 if [[ -f $path/xhttp.tar.gz ]];then
  warn "$(L '此备份包含独立 XHTTP 存档；请通过 b → 11 → 10 恢复 xhttp.tar.gz，sing-box 恢复不会覆盖当前 XHTTP。' 'This snapshot includes an independent XHTTP archive. Restore xhttp.tar.gz through b → 11 → 10; sing-box restore preserves current XHTTP.')"
 fi
 restore_done=true
 ok "$(L '配置已恢复；需要跳跃时请重新开启' 'Configuration restored; re-enable hopping if needed')"
)
restore_cleanup(){
 local rc=$? failed=false service active enabled
 if [[ ${restore_started:-false} == true && ${restore_done:-false} != true ]];then
  users_stop || failed=true
  backup_engine restore_rollback "$restore_stage" || failed=true
  warp_restore_snapshot "$snap" || failed=true
  argo_restore_snapshot "$snap" || failed=true
  users_restore_snapshot "$snap" || failed=true
  if [[ -f $restore_stage/services ]];then
   while read -r service active enabled;do
    if [[ $enabled == true ]];then systemctl enable "$service" || failed=true;else systemctl disable "$service" || failed=true;fi
    if [[ $active == true ]];then systemctl restart "$service" || failed=true;else systemctl stop "$service" || failed=true;fi
   done < "$restore_stage/services"
  fi
  exports >/dev/null || failed=true
  if [[ -f $BASE/users.json ]];then users_engine export_all | while IFS= read -r service;do users_export "$service" >/dev/null || return 1;done || failed=true;fi
  if [[ $failed == true ]];then err "$(L "恢复失败，回滚未全部完成；保留事务：$restore_stage；备份：$snap" "Restore failed; rollback incomplete. Transaction retained: $restore_stage; backup: $snap")"
  else err "$(L '恢复失败，已恢复原文件和服务状态' 'Restore failed; original files and service states restored')";fi
 fi
 if [[ -n ${restore_stage:-} && $failed == false ]];then rm -rf -- "$restore_stage";fi
 return "$rc"
}
# Optional fresh-server preparation. No SSH, firewall, kernel or reboot changes.
