# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
# lib/configuration.sh — build-time module; assembled by scripts/build.py.
edit_nodes(){
 local choice kind value stage cert private_key host node_port path
 local flags=()
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 menu '1. 重命名
2. 删除协议
3. 更新 TLS 证书
4. 修改地址/端口/路径
5. 修改节点端口
0. 返回' '1. Rename
2. Remove protocol
3. Refresh TLS certificate
4. Edit address/port/path
5. Change node port
0. Back'
 [[ ${1:-} != --menu ]] || return 0
 choice=$(ask '> ' '> ') || return 1
 else
  choice=$1
 fi
 [[ $choice != 0 ]] || return 0
 case $choice in 1|2|3|4|5) :;; *) error '选项无效。' 'Invalid option.';return 1;; esac
 if [[ $choice == 5 ]];then
  kind=$(choose_port_node) || return 0
  edit_node_port "$kind";return
 fi
 kind=$(choose_kind) || return 0
 case $choice in
  1) value=$(ask '新的节点名称：' 'New node name: ') || return 1; stage=$(helper rename --kind "$kind" --name "$value") || return 1;;
  2) confirm '删除该协议？重新安装会生成新凭据。' 'Remove protocol? Reinstallation generates new credentials.' || return 0
     stage=$(helper remove --kind "$kind") || return 1;;
  3) [[ $kind == xhttp-tls ]] || return 1
     cert=$(ask '新的 fullchain 证书绝对路径：' 'New fullchain certificate absolute path: ') || return 1
     private_key=$(ask '匹配的私钥绝对路径：' 'Matching private-key absolute path: ') || return 1
     stage=$(helper refresh-tls --kind "$kind" --cert "$cert" --key "$private_key") || return 1;;
  4) helper show || return 1
     warn '回车保留原值；修改后请重新导入客户端，并放行新 TCP 端口。TLS SNI 与证书保持原值。' 'Enter keeps the current value; re-import clients after editing and allow the new TCP port. TLS SNI and certificates are preserved.'
     host=$(ask '新的客户端连接地址 [保留]：' 'New client connection address [keep]: ') || return 1
     node_port=$(ask '新的监听 TCP 端口 [保留]：' 'New TCP listen port [keep]: ') || return 1
     [[ -z $host ]] || flags+=(--address "$host")
     [[ -z $node_port ]] || flags+=(--port "$node_port")
     if [[ $kind == xhttp-* ]]; then
      path=$(ask '新的 XHTTP 路径 [保留]：' 'New XHTTP path [keep]: ') || return 1
      [[ -z $path ]] || flags+=(--path "$path")
     fi
     (( ${#flags[@]} )) || return 0
     stage=$(helper edit --kind "$kind" "${flags[@]}") || return 1;;
  *) return 1;;
 esac
 apply_stage "$stage" || return 1
 if [[ $choice == 4 ]]; then
  say '节点已更新；请使用菜单 b 的新链接或导出文件更新客户端。' 'Node updated; update clients with the new links or exports from menu b.'
 fi
}
choose_port_node(){
 local kinds kind selection index=1
 local port_node_kinds=()
 kinds=$(helper node-kinds) || return 1
 while IFS= read -r kind;do [[ -z $kind ]] || port_node_kinds+=("$kind");done <<< "$kinds"
 if [[ ${#port_node_kinds[@]} == 1 ]];then printf '%s' "${port_node_kinds[0]}";return;fi
 for kind in "${port_node_kinds[@]}";do printf '%s. %s\n' "$index" "$kind" >&2;index=$((index+1));done
 say '0. 返回' '0. Back' >&2
 selection=$(ask '选择要修改端口的节点：' 'Select a node to change its port: ') || return 1
 [[ $selection =~ ^[1-3]$ ]] && (( selection <= ${#port_node_kinds[@]} )) || return 1
 printf '%s' "${port_node_kinds[$((selection-1))]}"
}
edit_node_port(){
 local kind=$1 current value stage opened=false firewall_state
 current=$(helper node-port --kind "$kind") || return 1
 report_output say "当前节点：$kind" "Current node: $kind"
 value=$(ask "当前 TCP 端口 ${current}，新端口（回车保留）：" "Current TCP port $current; new port (Enter keeps it): ") || return 0
 if [[ -z $value || $value == "$current" ]];then say '端口未变更。' 'Port unchanged.';return 0;fi
 if [[ ! $value =~ ^[0-9]{1,5}$ ]] || (( 10#$value < 1 || 10#$value > 65535 ));then error '端口须为 1–65535。' 'Use a port from 1 to 65535.';return 1;fi
 value=$((10#$value))
 if [[ $value == "$current" ]];then say '端口未变更。' 'Port unchanged.';return 0;fi
 say "TCP：$current → $value" "TCP: $current → $value"
 warn '保留 UUID、密钥、Short ID、握手网站和路径；运行中的节点会短暂重载。已启用 UFW 时放行新端口，云安全组或 firewalld 仍需自行核对。' 'Keeps UUID, keys, Short ID, handshake site and path. Running nodes briefly reload. Active UFW allows the new port; verify provider firewall/firewalld rules separately.'
 confirm '应用端口变更？' 'Apply this port change?' || { say '已取消，端口未变更。' 'Cancelled; port unchanged.';return 0; }
 stage=$(helper edit --kind "$kind" --port "$value") || return 1
 # Keep the current listener until any required UFW rule succeeds.
 firewall_state=$(helper ufw-state) || { helper finalize --stage "$stage" || true;error '无法读取 UFW 状态，节点端口未修改。' 'Cannot inspect UFW; node port unchanged.';return 1; }
 if [[ $firewall_state == active ]];then
  if ! helper firewall-allow --ports "$value";then
   helper finalize --stage "$stage" || true
   error 'UFW 放行未完成，节点端口未修改；请核对防火墙规则。' 'UFW allow incomplete; node port unchanged. Inspect firewall rules.'
   return 1
  fi
  opened=true
 fi
 if ! apply_stage "$stage";then
  [[ $opened != true ]] || warn '节点更新失败，已尝试回退；新端口的 UFW 放行规则保留，请在防火墙菜单核对。' 'Node update failed; rollback attempted. The new UFW allow rule is retained; review it in the firewall menu.'
  return 1
 fi
 say '端口已更新；从 b 获取新节点并重新导入客户端，IPv6 备用同步更新。旧防火墙规则保留。' 'Port updated. Get new nodes from b and re-import them; IPv6 backups are updated too. Old firewall rules are retained.'
}
