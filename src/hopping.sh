hop_guard(){
 local unit=$SYSTEMD_DIR/singbox-v2-hop.service file
 for file in hop.nft hop-iptables.sh; do [[ ! -L $BASE/$file ]] || return 1; done
 if [[ -e $unit || -L $unit ]]; then
  if [[ -L $unit ]] || ! grep -Fxq 'Description=singbox V2 HY2 IPv4 port hopping' "$unit"; then err "$(L '端口跳跃服务归属异常' 'Hopping service ownership mismatch')"; return 1; fi
  if grep -Fxq "ExecStart=/usr/sbin/nft -f $BASE/hop.nft" "$unit"; then :
  elif grep -Fxq "ExecStart=/bin/bash $BASE/hop-iptables.sh start" "$unit" && grep -Fxq "ExecStop=/bin/bash $BASE/hop-iptables.sh stop" "$unit" && [[ -f $BASE/hop-iptables.sh ]] && grep -Fxq '# SKYBYTE managed HY2 hopping' "$BASE/hop-iptables.sh"; then :
  else err "$(L '端口跳跃启动路径异常，拒绝操作' 'Hopping executable mismatch; refusing operation')"; return 1; fi
 fi
}
hop_disable(){
 hop_guard || return 1
 local unit=$SYSTEMD_DIR/singbox-v2-hop.service
 if [[ -f $unit ]]; then
  systemctl disable --now singbox-v2-hop.service || return 1
  if grep -Fxq "ExecStart=/usr/sbin/nft -f $BASE/hop.nft" "$unit"; then nft delete table ip singbox_v2_hop 2>/dev/null || :; fi
 fi
 if [[ -f $META ]]; then python3 - "$META" <<'PY_HOP_OFF'
import json,sys
p=sys.argv[1];d=json.load(open(p));d['hop']=False
with open(p,'w') as f:json.dump(d,f,indent=2)
PY_HOP_OFF
 fi
 say '已关闭托管的端口跳跃；UFW/云防火墙规则请按需要清理。' 'Managed hopping disabled; clean up UFW/provider rules as needed.'
}
hop(){
 check_owned && hop_guard || return 1
 [[ $(protocol_mode) != 1 ]] || { err "$(L '未安装 HY2' 'HY2 not installed')"; return 1; }
 local choice backend start end target
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 say '端口跳跃仅支持 IPv4；规则随 systemd 开机恢复，需要放行云防火墙 UDP 范围。' 'Hopping is IPv4-only, persisted with systemd; allow the provider UDP range.'
 prompt_options '1 开启  2 关闭  0 返回' '1 Enable  2 Disable  0 Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
 if [[ $choice == 2 ]]; then confirm "$(L '关闭跳跃？' 'Disable hopping?')" && hop_disable; return; fi
 [[ $choice == 1 ]] || return 0
 prompt_options '1 nftables（默认）  2 iptables' '1 nftables (default)  2 iptables'
 prompt_read '> ' backend || return 0; backend=${backend:-1}
 case $backend in 1) backend=nftables;; 2) backend=iptables;; *) return 1;; esac
 prompt_read "$(L '起始端口 [20000]：' 'Start port [20000]: ')" start || return 0; start=${start:-20000}
 prompt_read "$(L '结束端口 [40000]：' 'End port [40000]: ')" end || return 0; end=${end:-40000}
 if ! valid_port "$start" || ! valid_port "$end" || ! ((10#$start>=1024 && 10#$start<=10#$end && 10#$end-10#$start<=20000)); then err "$(L '范围非法，最多20001个端口' 'Invalid range, maximum 20001 ports')"; return 1; fi
 start=$((10#$start));end=$((10#$end));target=$(protocol_port hysteria2) || return 1
 if [[ -f $BASE/users.json ]]; then users_guard && users_engine hop_check "$start" "$end" || return 1; fi
 confirm "$(L "将 UDP $start-$end 转发到 HY2 监听端口 ${target}？" "Forward UDP $start-$end to HY2 listener $target?")" || return 0
 if [[ $backend == nftables ]]; then require_cmd nft || return 1; else command -v iptables >/dev/null || { apt_install iptables || return 1; }; fi
 if command -v nft >/dev/null && nft list table ip singbox_v2_hop >/dev/null 2>&1; then err "$(L '已有跳跃规则，请先关闭' 'Hopping rules exist; disable first')"; return 1; fi
 if command -v iptables >/dev/null && iptables -w 5 -t nat -S SKYBYTE_HY2_HOP >/dev/null 2>&1; then err "$(L '已有跳跃链，请先关闭，拒绝覆盖' 'Hopping chain exists; disable first; refusing overwrite')"; return 1; fi
 if [[ $backend == nftables ]]; then
 cat >"$BASE/hop.nft" <<RULES
add table ip singbox_v2_hop
add chain ip singbox_v2_hop prerouting { type nat hook prerouting priority dstnat; policy accept; }
add rule ip singbox_v2_hop prerouting udp dport $start-$end redirect to :$target
RULES
 cat >"$SYSTEMD_DIR/singbox-v2-hop.service" <<UNIT
[Unit]
Description=singbox V2 HY2 IPv4 port hopping
After=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f $BASE/hop.nft
ExecStop=/usr/sbin/nft delete table ip singbox_v2_hop
[Install]
WantedBy=multi-user.target
UNIT
 else
 cat >"$BASE/hop-iptables.sh" <<SCRIPT
#!/usr/bin/env bash
# SKYBYTE managed HY2 hopping
set -Eeuo pipefail
case \${1:-} in
 start)
  iptables -w 5 -t nat -N SKYBYTE_HY2_HOP
  if ! iptables -w 5 -t nat -A SKYBYTE_HY2_HOP -p udp -j REDIRECT --to-ports $target || ! iptables -w 5 -t nat -A PREROUTING -p udp --dport $start:$end -j SKYBYTE_HY2_HOP; then
   iptables -w 5 -t nat -F SKYBYTE_HY2_HOP; iptables -w 5 -t nat -X SKYBYTE_HY2_HOP; exit 1
  fi;;
 stop)
  iptables -w 5 -t nat -D PREROUTING -p udp --dport $start:$end -j SKYBYTE_HY2_HOP || :
  iptables -w 5 -t nat -F SKYBYTE_HY2_HOP || :
  iptables -w 5 -t nat -X SKYBYTE_HY2_HOP || :;;
 *) exit 1;;
esac
SCRIPT
 chmod 700 "$BASE/hop-iptables.sh"
 cat >"$SYSTEMD_DIR/singbox-v2-hop.service" <<UNIT
[Unit]
Description=singbox V2 HY2 IPv4 port hopping
After=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash $BASE/hop-iptables.sh start
ExecStop=/bin/bash $BASE/hop-iptables.sh stop
[Install]
WantedBy=multi-user.target
UNIT
 fi
 if ! systemctl daemon-reload || ! systemctl enable --now singbox-v2-hop.service; then
  systemctl stop singbox-v2-hop.service || :; err "$(L '跳跃规则启用失败' 'Hopping enable failed')"; return 1
 fi
 python3 - "$META" "$start" "$end" "$backend" "$target" <<'PY_HOP_ON'
import json,sys
p=sys.argv[1];d=json.load(open(p));d.update(hop=True,hop_start=int(sys.argv[2]),hop_end=int(sys.argv[3]),hop_backend=sys.argv[4],hop_target=int(sys.argv[5]))
with open(p,'w') as f:json.dump(d,f,indent=2)
PY_HOP_ON
 if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active'; then ufw allow "$start:$end/udp" || return 1; fi
 exports
 say '客户端 JSON/YAML 已加入跳跃范围；小火箭请在客户端配置跳跃范围。云安全组也必须放行此范围。' 'JSON/YAML includes hopping ranges; configure hopping manually in Shadowrocket. Allow the provider UDP range too.'
}
