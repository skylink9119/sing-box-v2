# lib/service.sh — build-time module; assembled by scripts/build.py.
download_binary(){
 local version=$1 target=$2 arch tmp asset sum
 [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
 arch=$(rescue_engine arch "$(uname -m)" sing-box) || return 1
 if [[ -n ${SKYBYTE_ASSET_DIR:-} ]];then rescue_engine asset "$SKYBYTE_ASSET_DIR" sing-box "$version" "$(uname -m)" "$target";return $?;fi
 tmp=$(mktemp -d) || return 1
 asset="sing-box-$version-linux-$arch.tar.gz"
 if ! curl -q -fsSL --connect-timeout 10 --proto '=https' --proto-redir '=https' --retry 2 --max-time 180 "https://github.com/SagerNet/sing-box/releases/download/v$version/$asset" -o "$tmp/$asset" ||
    ! curl -q -fsSL --connect-timeout 10 --proto '=https' --proto-redir '=https' --retry 2 --max-time 30 "https://api.github.com/repos/SagerNet/sing-box/releases/tags/v$version" -o "$tmp/release.json"; then rm -rf "$tmp"; return 1; fi
 sum=$(python3 - "$tmp/release.json" "$asset" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); assert not r['draft'] and not r['prerelease']
a=next(a for a in r['assets'] if a['name']==sys.argv[2])
digest=a.get('digest') or ''; assert digest.startswith('sha256:')
print(digest.split(':',1)[1])
PY
 ) || { rm -rf "$tmp"; return 1; }
 if [[ ! $sum =~ ^[a-fA-F0-9]{64}$ ]] || ! printf '%s  %s\n' "$sum" "$tmp/$asset" | sha256sum -c - >/dev/null; then rm -rf "$tmp"; return 1; fi
 tar -xzf "$tmp/$asset" -C "$tmp" || { rm -rf "$tmp"; return 1; }
 command install -m 755 "$tmp/sing-box-$version-linux-$arch/sing-box" "$target"
 local rc=$?; rm -rf "$tmp"; return "$rc"
}
setup_service(){ cat >"$SYSTEMD_DIR/sing-box.service" <<EOF
[Unit]
Description=sing-box (managed by singbox-v2)
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=$BIN run -c $CONF
Restart=on-failure
RestartSec=3
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
EOF
 systemctl daemon-reload; }
# Installation requires a clean deployment; configuration generation is separately testable.
latest(){ curl -q -fsSL --connect-timeout 10 --proto '=https' --proto-redir '=https' --max-time 25 https://api.github.com/repos/SagerNet/sing-box/releases/latest | python3 -c 'import json,sys; d=json.load(sys.stdin); assert not d.get("prerelease") and not d.get("draft"); print(d["tag_name"].lstrip("v"))'; }
update(){
 check_owned || return 1
 local new current
 current=$("$BIN" version | awk 'NR==1{print $3}'); new=$(latest) || return 1
 printf '%s -> %s\n' "$current" "$new"
 [[ $current != "$new" ]] || return 0
 confirm "$(L '更新会短暂中断连接，继续？' 'Update briefly interrupts connections. Continue?')" || return 0
 apply_update "$new"
}
managed_restart(){
 local argo_active=false tunnel_active=false users_active=false
 if [[ -f $BASE/warp-gateway.json ]] && systemctl is-active --quiet skybyte-warp-gateway.service; then systemctl restart skybyte-warp-gateway.service && systemctl is-active --quiet skybyte-warp-gateway.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/skybyte-argo-node.service ]] && systemctl is-active --quiet skybyte-argo-node.service; then argo_active=true; fi
 if [[ -f $SYSTEMD_DIR/skybyte-argo-tunnel.service ]] && systemctl is-active --quiet skybyte-argo-tunnel.service; then tunnel_active=true; fi
 if [[ -f $BASE/users.json ]] && systemctl is-active --quiet skybyte-users.service; then users_guard || return 1; users_active=true; fi
 admin_restart || return 1
 if [[ $argo_active == true ]]; then
  systemctl restart skybyte-argo-node.service && systemctl is-active --quiet skybyte-argo-node.service || return 1
  if [[ $tunnel_active == true ]]; then systemctl restart skybyte-argo-tunnel.service || return 1; fi
 fi
 if [[ $users_active == true ]]; then systemctl restart skybyte-users.service || return 1; fi
}
apply_update(){
 local new=$1 snap candidate
 candidate=$(mktemp "$BASE/sing-box.candidate.XXXXXX") || return 1
 snap=$(backup) || { rm -f "$candidate"; return 1; }
 download_binary "$new" "$candidate" || { rm -f "$candidate"; return 1; }
 if [[ -f $BASE/warp-gateway.json ]]; then "$candidate" check -c "$BASE/warp-gateway.json" || { rm -f "$candidate"; return 1; }; fi
 "$candidate" check -c "$CONF" || { rm -f "$candidate"; return 1; }
 if [[ -f $BASE/argo-server.json ]]; then "$candidate" check -c "$BASE/argo-server.json" || { rm -f "$candidate"; return 1; }; fi
 if [[ -f $BASE/users.json ]]; then if ! users_guard || ! users_engine validate "$candidate"; then rm -f "$candidate"; return 1; fi; fi
 command install -m 755 "$candidate" "$BIN" || return 1; rm -f "$candidate"
 if ! managed_restart; then
  command install -m 755 "$snap/sing-box.bin" "$BIN"; warp_restore_snapshot "$snap" || :; admin_restart || :; argo_restore_snapshot "$snap" || :; users_restore_snapshot "$snap" || :
  err "$(L '更新失败，已恢复原二进制' 'Update failed; original binary restored')"; return 1
 fi
 python3 - "$BASE/core-version.json" "$new" "$CORE_RECOMMENDED" <<'PY_CORE_VERSION'
import json,os,pathlib,sys,tempfile,time
p=pathlib.Path(sys.argv[1]);assert not p.is_symlink()
fd,tmp=tempfile.mkstemp(dir=p.parent)
with os.fdopen(fd,'w') as f:json.dump({'owner':'SKYBYTE core version v1','version':sys.argv[2],'tested':sys.argv[3],'updated_at':int(time.time())},f)
os.replace(tmp,p)
PY_CORE_VERSION
 ok "$(L '更新完成，请检查客户端连接' 'Updated; verify client connectivity')"
}
service_healthy(){ sleep 2; systemctl is-active --quiet sing-box; }
retire_auto_update(){
 local unit timer saved
 unit=$SYSTEMD_DIR/singbox-v2-update.service;timer=$SYSTEMD_DIR/singbox-v2-update.timer
 [[ -e $unit || -e $timer || -L $unit || -L $timer ]] || return 0
 if [[ -L $unit || -L $timer ]] || { [[ -f $unit ]] && { ! grep -Fxq 'Description=sing-box v2 weekly update' "$unit" || ! grep -Fxq "ExecStart=/bin/bash $MANAGER_BIN --auto-update" "$unit"; }; } || { [[ -f $timer ]] && ! grep -Fxq 'Description=sing-box v2 weekly update timer' "$timer"; }; then
  warn "$(L '旧更新服务归属异常，保留不修改' 'Legacy update unit ownership mismatch; retained')"; return 0
 fi
 mkdir -p "$BASE/manager-backups"
 saved=$(mktemp -d "$BASE/manager-backups/legacy-auto.XXXXXX") || return 1
 [[ ! -f $unit ]] || cp "$unit" "$saved/" || return 1
 [[ ! -f $timer ]] || cp "$timer" "$saved/" || return 1
 [[ ! -f $timer ]] || systemctl disable --now singbox-v2-update.timer || return 1
 [[ ! -f $unit ]] || systemctl stop singbox-v2-update.service || return 1
 rm -f "$unit" "$timer";systemctl daemon-reload || return 1
 say "已停用旧每周更新，服务文件备份：$saved" "Legacy weekly updater retired; unit backups: $saved"
}
update_auto(){ warn "$(L '每周自动更新已移除，请使用手动更新' 'Weekly updates removed; use manual updates')"; }
status(){
 systemctl --no-pager status sing-box 2>&1 | head -25 || :
 local protocol port
 if [[ -f $CONF ]];then
  for protocol in vless hysteria2;do
   if port=$(protocol_port "$protocol" 2>/dev/null);then
    printf '%s: %s\n' "$protocol" "$port"
    if [[ $protocol == vless ]];then ss -ltn "( sport = :$port )";else ss -lun "( sport = :$port )";fi
   fi
  done
 fi
 echo 'UFW:';firewall_audit;echo 'Hop:'
 if [[ -f $META && $(state hop_backend) == iptables ]];then iptables -w 5 -t nat -S SKYBYTE_HY2_HOP 2>/dev/null || :;else nft list table ip singbox_v2_hop 2>/dev/null || :;fi
}
service_manager(){
 local x
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 prompt_options '1. 状态
2. 启动
3. 重启
4. 停止
5. 开机自启
6. 配置检查
0. 返回' '1. Status
2. Start
3. Restart
4. Stop
5. Enable at boot
6. Config check
0. Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' x || return
 else
  x=$1
 fi
 case "$x" in
  1) report_output status ;;
  2|3|4|5)
   check_owned || return 1
   case "$x" in
    2) confirm "$(L '启动 sing-box？' 'Start sing-box?')" || return 0
       systemctl start sing-box ;;
    3) confirm "$(L '重启 sing-box？' 'Restart sing-box?')" || return 0
       "$BIN" check -c "$CONF" || return 1
       systemctl restart sing-box ;;
    4) warn "$(L '管理员直连节点将断开连接；Argo 和受限用户请单独管理' 'Admin direct nodes will disconnect; manage Argo and quota users separately')"
       confirm "$(L '停止 sing-box？' 'Stop sing-box?')" || return 0
       systemctl stop sing-box ;;
    5) confirm "$(L '设置开机自启？' 'Enable sing-box at boot?')" || return 0
       systemctl enable sing-box ;;
   esac ;;
  6) check_owned && "$BIN" check -c "$CONF" ;;
  0) return 0 ;;
  *) err "$(L '无效选择' 'Invalid choice')"; return 1 ;;
 esac
}
