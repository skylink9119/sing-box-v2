haproxy_engine(){
 local output rc=0
 output=$(python3 - "$BASE" "$SYSTEMD_DIR" "$HAPROXY_BIN" "$CONF" "$@" 2>&1 <<'PY_HAPROXY'
# @include haproxy.py
PY_HAPROXY
 ) || rc=$?
 if ((rc));then err "$output";return "$rc";fi
 [[ -z $output ]] || printf '%s%s%s\n' "$YELLOW" "$output" "$RESET"
 return 0
}
haproxy_guard(){ haproxy_engine guard; }
haproxy_install_binary() (
 [[ ! -L $HAPROXY_BIN ]] || return 1
 [[ ! -x $HAPROXY_BIN ]] || return 0
 require_cmd apt-get && require_cmd systemctl || return 1
 if systemctl is-active --quiet haproxy.service;then
  err "$(L '已有运行中的非托管 HAProxy，请先修复其二进制路径' 'An external HAProxy service is active; repair its binary path first')";return 1
 fi
 local mask=$HAPROXY_RUNTIME_DIR/haproxy.service created=false enabled=false completed=false
 if systemctl is-enabled --quiet haproxy.service;then enabled=true;fi
 trap haproxy_install_cleanup EXIT
 mkdir -p "$HAPROXY_RUNTIME_DIR" || return 1
 if [[ ! -e $mask && ! -L $mask ]];then
  ln -s /dev/null "$mask" || return 1;created=true
  systemctl daemon-reload || return 1
 fi
 apt_install -o Dpkg::Options::=--force-confold --no-install-recommends haproxy || return 1
 [[ -x $HAPROXY_BIN ]] || return 1
 # A newly installed package must not start its default listener at the next boot.
 if [[ $enabled == false ]];then systemctl disable haproxy.service || return 1;fi
 completed=true
)
haproxy_install_cleanup(){
 if [[ ${completed:-false} == false && ${enabled:-false} == false ]];then
  systemctl disable haproxy.service >/dev/null 2>&1 || :
 fi
 if [[ ${created:-false} == true && -L ${mask:-} && $(readlink "$mask") == /dev/null ]];then
  rm -f -- "$mask";systemctl daemon-reload >/dev/null 2>&1 || :
 fi
}
haproxy_add(){
 local name listen port peer peer_port id=${1:-}
 prompt_read "$(L '规则名称 [SKYBYTE-TCP]：' 'Rule name [SKYBYTE-TCP]: ')" name || return 0
 prompt_read "$(L 'A 监听地址 [0.0.0.0]（IPv6 可填 ::）：' 'A listen IP [0.0.0.0] (IPv6: ::): ')" listen || return 0
 prompt_read "$(L 'A 转发 TCP 端口 [8443]：' 'A forwarding TCP port [8443]: ')" port || return 0;port=${port:-8443}
 prompt_read "$(L 'B 落地 IP / 域名（只填地址）：' 'B landing IP / hostname (address only): ')" peer || return 0
 prompt_read "$(L 'B 节点 TCP 端口 [443]：' 'B node TCP port [443]: ')" peer_port || return 0;peer_port=${peer_port:-443}
 valid_port "$port" && valid_port "$peer_port" || return 1
 [[ $peer =~ ^[a-zA-Z0-9:.-]+$ && ${#peer} -le 253 ]] || { err "$(L 'B 只填写 IP 或域名，请勿粘贴节点链接' 'Enter only B IP/hostname; do not paste a node URI')";return 1; }
 warn "$(L '添加或修改 TCP 转发会启用独立 HAProxy 服务，已有 TCP 转发连接可能短暂中断。B 的协议必须使用 TCP；HY2 不支持此模式。' 'Adding or editing TCP forwarding enables a separate HAProxy service; existing forwarded connections may briefly disconnect. B must use TCP; HY2 is unsupported in this mode.')"
 confirm "$(L '检查 B 的 TCP 可达性并启用转发？' 'Check B TCP reachability and enable forwarding?')" || return 0
 haproxy_install_binary || return 1
 if [[ -n $id ]];then haproxy_engine edit "$id" "$name" "$listen" "$port" "$peer" "$peer_port" || return 1
 else haproxy_engine add "$name" "$listen" "$port" "$peer" "$peer_port" || return 1;fi
 if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active';then
  if ! ufw allow "$port/tcp";then warn "$(L 'HAProxy 已启用，但 UFW 放行失败；请人工检查防火墙。' 'HAProxy is enabled, but UFW access failed; check firewall rules manually.')";fi
 fi
 printf '%s' "$YELLOW"
 say "A 转发端口：TCP ${port}；B 节点端口：TCP ${peer_port}。请在云防火墙放行 A 的入口及 A → B 的 TCP 连接。" "A entry: TCP $port; B node: TCP $peer_port. Allow A ingress and A → B TCP access in provider firewalls."
 say '手机复制 B 的节点，仅把连接地址与端口改为 A 的公网地址和转发端口；保留 B 的认证、SNI、Reality 公钥及证书验证。' "On your phone, copy B's node and change only the connection address/port to A's public address/forwarding port. Retain B's authentication, SNI, Reality public key and certificate verification."
 printf '%s' "$RESET"
}
haproxy_help(){
 printf '%s' "$YELLOW"
 if [[ ${LANGUAGE_CHOICE:-zh_CN} == en_US ]];then cat <<'HAPROXY_HELP_EN'
HAProxy TCP passthrough — usage guide

A: entry server with a good client-facing route. B: residential exit server.
Path: phone → A HAProxy TCP forwarder → B node → website.

1. On B, prepare a working TCP node, such as VLESS + Reality + Vision or Trojan.
   Keep B's egress direct to retain its residential IP. Allow B's actual TCP node port from A.
2. On A, open 4 → 11 HAProxy TCP passthrough, then 1 Add TCP rule.
   A does not need a sing-box node for this mode.
3. Enter a rule name, A's listen IP and TCP port, then B's IP/hostname and node TCP port.
   Defaults: A listens on 0.0.0.0:8443, B uses port 443. IPv6 listen :: is IPv6-only.
   Use an unused port on A. Type y to validate and enable forwarding.
4. On your phone, copy B's node. Change only its connection address to A's public IP/hostname
   and its connection port to A's forwarding port. Keep B's password/UUID, SNI, Reality keys,
   fingerprint and certificate verification settings. A does not need B's private key.
5. Connect with the edited node in Shadowrocket. Websites should see B's actual exit IP.
   B handles node authentication, per-user usage, quotas and expiry. Manage users on B.

This mode passes TCP bytes without terminating TLS. A does not require B's public CA file;
the phone must still securely trust B's certificate if B uses self-signed TLS.
It does not forward HY2/QUIC/raw UDP. Protocol-carried UDP inside a TCP node depends on B/client support.
TCP reachability checks do not verify node authentication, streaming access or speed improvements.
Open A's forwarding TCP port in UFW/provider rules; B must allow A's TCP connections.
DNS targets are re-resolved; keep aliases from pointing back to any entry rule to avoid loops.
Standalone backups are under /etc/singbox-v2/haproxy-backups. Full manager backups also include
a haproxy subdirectory; restore that separately through this menu (10) after restoring sing-box.
Only the owned skybyte-haproxy.service and /etc/singbox-v2/haproxy files are managed.
Use menu 2 to edit a rule by ID. If B changes, update B's credentials/SNI on the phone as needed.
Existing /etc/haproxy/haproxy.cfg, external services and firewall rules are preserved.
The forwarding endpoint must be protected by B's authenticated node; use your own trusted B.
HAPROXY_HELP_EN
 else cat <<'HAPROXY_HELP_ZH'
HAProxy TCP 透传 — 使用说明

A：线路较好的中转服务器。B：住宅 IP 落地服务器。
路径：手机 → A 的 HAProxy TCP 转发 → B 的节点 → 网站。

1. 打开 B 的终端，准备可用的 TCP 节点，例如 VLESS + Reality + Vision 或 Trojan。
   B 出站保持直连以保留住宅 IP，放行 A 到 B 的实际 TCP 节点端口。
2. 切换到 A 的终端，进入 4 → 11「HAProxy TCP 透传」，选择 1「添加 TCP 规则」。
   这种模式下，A 可以不安装 sing-box 节点。
3. 填写规则名称、A 监听地址与转发端口，再填写 B 的 IP / 域名和节点 TCP 端口。
   默认 A 监听 0.0.0.0:8443，B 端口为 443；IPv6 监听可填 ::，仅接收 IPv6。
   A 的端口必须未被占用。输入 y，检查后启用转发。
4. 在手机上复制 B 的节点，只把连接地址改为 A 的公网 IP / 域名，端口改为 A 的转发端口。
   保留 B 的密码 / UUID、SNI、Reality 公钥、指纹及证书验证设置。A 不需要 B 的私钥。
5. 小火箭连接修改后的节点，网站看到的出口应为 B。
   节点认证、每人用量、配额和有效期都由 B 管理，请在 B 上添加用户。

此模式原样转发 TCP 数据，不终止 TLS。A 不需要复制 B 的公开 CA 文件；
如果 B 使用自签名 TLS，手机仍需安全地信任 B 的证书。
不转发 HY2 / QUIC / 原生 UDP；TCP 节点内封装的 UDP 能否使用取决于 B 与客户端。
TCP 可达性检查不代表节点认证通过、流媒体解锁或实际提速。
请放行 A 的转发 TCP 端口（UFW 与云防火墙），并确保 B 允许 A 的 TCP 连接。
域名落地会动态解析，勿将别名指向 A 的任意转发入口，以免产生回环。
独立备份在 /etc/singbox-v2/haproxy-backups；完整管理备份也包含 haproxy 子目录。
恢复 sing-box 后，在本菜单 10 单独恢复该子目录，不自动覆盖现有 TCP 转发规则。
仅管理 skybyte-haproxy.service 和 /etc/singbox-v2/haproxy 中的托管文件。
菜单 2 可按 ID 修改规则；更换 B 后，手机的认证与 SNI 等参数也需按新的 B 更新。
现有 /etc/haproxy/haproxy.cfg、其他服务和防火墙规则均保留。
转发入口应由 B 的节点认证保护，请使用自己控制的可信 B。
HAPROXY_HELP_ZH
 fi
 printf '%s' "$RESET"
}
haproxy_menu(){
 haproxy_guard || return 1
 local choice value
 printf '%s' "$YELLOW"
 say 'TCP 透传：手机使用 B 的节点参数，连接 A 的转发端口；用量与配额在 B 管理。' "TCP passthrough: the phone uses B's node parameters through A's forwarding port; manage usage/quotas on B."
 printf '%s' "$RESET"
 prompt_options $' 1. 添加 TCP 规则\n 2. 修改 TCP 规则\n 3. 规则与状态\n 4. 启动与开机自启\n 5. 停止并关闭自启\n 6. 重启\n 7. 测试 B 的 TCP 连接\n 8. 删除规则\n 9. 备份\n10. 恢复\n11. 卸载 HAProxy 中转\n12. 使用说明\n 0. 返回' $' 1. Add TCP rule\n 2. Edit TCP rule\n 3. Rules/status\n 4. Start/enable at boot\n 5. Stop/disable at boot\n 6. Restart\n 7. Test B TCP\n 8. Remove rule\n 9. Backup\n10. Restore\n11. Uninstall HAProxy relay\n12. Usage guide\n 0. Back'
 prompt_read '> ' choice || return 0
 case $choice in
  0) return 0;;12) haproxy_help;;
  1) haproxy_add;;
  2) haproxy_engine list;prompt_read "$(L '要修改的规则 ID（重新填写该规则参数）：' 'Rule ID to edit (re-enter its parameters): ')" value || return 0;[[ $value =~ ^[a-f0-9]{12}$ ]] || { err "$(L '规则 ID 无效' 'Invalid rule ID')";return 1; };haproxy_engine check_id "$value" && haproxy_add "$value";;
  3) haproxy_engine list;[[ ! -d $BASE/haproxy ]] || systemctl --no-pager status skybyte-haproxy.service || :;;
  4) confirm "$(L '启动并启用开机自启？' 'Start and enable at boot?')" && haproxy_install_binary && haproxy_engine start;;
  5) confirm "$(L '停止 TCP 转发并关闭开机自启？' 'Stop TCP forwarding and disable at boot?')" && haproxy_engine stop;;
  6) confirm "$(L '重启 TCP 转发？现有转发连接可能断开。' 'Restart TCP forwarding? Existing connections may disconnect.')" && haproxy_engine restart;;
  7) haproxy_engine probe;;
  8) haproxy_engine list;prompt_read "$(L '要删除的规则 ID：' 'Rule ID to remove: ')" value || return 0;confirm "$(L '删除此规则？最后一条删除后服务也会移除。' 'Remove this rule? Removing the last rule also removes the service.')" && haproxy_engine remove "$value";;
  9) haproxy_engine backup;;
  10) say '填写独立备份目录，或完整备份中的 haproxy 子目录。恢复会替换现有 TCP 规则并按备份状态启停服务。' 'Supply a standalone backup directory or the haproxy subdirectory in a full backup. Restore replaces current TCP rules and restores saved service activity.';prompt_read "$(L 'HAProxy 备份目录：' 'HAProxy backup directory: ')" value || return 0;confirm "$(L '校验并恢复 HAProxy 规则？' 'Validate and restore HAProxy rules?')" && haproxy_install_binary && haproxy_engine restore "$value";;
  11) confirm "$(L '备份并卸载本工具的 HAProxy TCP 转发？保留软件包、外部配置与防火墙规则。' 'Back up and remove managed HAProxy TCP forwarding? Keep the package, external config and firewall rules.')" && haproxy_engine purge;;
  *) err "$(L '无效选项' 'Invalid choice')";return 1;;
 esac
}
