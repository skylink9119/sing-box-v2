# modules/hysteria2.sh — build-time module; assembled by scripts/build.py.
hy2_diagnostics(){
 check_owned || return 1
 local port details cert key name listener
 port=$(protocol_port hysteria2) || { err "$(L '未找到 HY2 入站' 'No HY2 inbound found')"; return 1; }
 say '---------------- HY2 连接诊断 ----------------' '---------------- HY2 connection checks ----------------'
 if "$BIN" check -c "$CONF"; then ok "$(L '服务端配置检查通过' 'Server configuration check passed')"; else err "$(L '服务端配置无效' 'Server configuration invalid')"; fi
 if systemctl is-active --quiet sing-box; then ok "$(L 'sing-box 服务正在运行' 'sing-box service is active')"; else err "$(L 'sing-box 服务未运行；请查看服务与日志 → 日志（c → 2） 日志' 'sing-box is not active; inspect Services and logs > Logs (c > 2) logs')"; fi
 listener=$(ss -H -lun "( sport = :$port )") || return 1
 if [[ -n $listener ]]; then ok "$(L "本机 UDP $port 有监听" "Local UDP $port has a listener")"; else err "$(L "本机 UDP $port 未监听" "No local UDP $port listener")"; fi
 details=$(python3 - "$CONF" <<'PY'
import json,sys
c=next(i for i in json.load(open(sys.argv[1]))['inbounds'] if i['type']=='hysteria2')['tls']
for field in ['certificate_path','key_path','server_name']:print(c[field])
PY
 ) || return 1
 { read -r cert; read -r key; read -r name; } <<<"$details"
 if validate_certificate "$cert" "$key" "$name"; then ok "$(L '证书有效期、名称与私钥匹配检查通过' 'Certificate expiry, name and key matching checks passed')"; else err "$(L '证书检查失败，请检查文件或证书身份' 'Certificate checks failed; inspect files and certificate identity')"; fi
 openssl x509 -in "$cert" -noout -dates -fingerprint -sha256 || return 1
 firewall_audit
 warn "$(L '本机检查不能证明手机到 VPS 的 UDP 可达，也不能证明小火箭已信任证书。' 'Local checks do not prove phone-to-VPS UDP reachability or Shadowrocket certificate trust.')"
 say 'certificate/x509 错误：检查客户端证书信任、SNI 和指纹。' 'certificate/x509 errors: check client certificate trust, SNI and fingerprint.'
 say 'timeout/no recent network activity：检查本机与云防火墙 UDP，换 Wi-Fi/移动网络测试。' 'timeout/no recent network activity: inspect local/provider UDP rules and try another Wi-Fi/mobile network.'
 say 'authentication failed：重新导出、导入节点，核对密码；不要公开节点链接。' 'authentication failed: re-export/import the node and verify password; do not publish the URI.'
 say '请用小火箭实际连接或 URL 测试；普通 ICMP 延迟不能验证 HY2。' 'Use an actual Shadowrocket connection or URL test; ICMP latency does not validate HY2.'
 printf '%s\n' "$(L '只读抓包命令（连接节点时执行；不显示数据包内容）：' 'Read-only packet check while connecting (does not display packet contents):')"
 printf '  sudo timeout 15 tcpdump -nn -i any "udp port %s"\n' "$port"
 say '---------------- 诊断结束 ----------------' '---------------- End of checks ----------------'
}
# @include modules/hopping.sh
