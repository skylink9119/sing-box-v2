change_node_ports(){
 local choice
 if [[ ! -f $BASE/xhttp/state.json ]];then edit_node_ports;return;fi
 if [[ ! -f $META || ! -f $CONF ]];then xhttp_command edit 5;return;fi
 prompt_options '选择要更换端口的节点：
1. Reality / Hysteria2
2. XHTTP
0. 返回' 'Select nodes to change ports:
1. Reality / Hysteria2
2. XHTTP
0. Back'
 prompt_read '> ' choice || return 0
 case $choice in
  1) edit_node_ports;;
  2) xhttp_command edit 5;;
  0) return 0;;
  *) return 1;;
 esac
}
port_check_tcp(){
 local host=${1:-} port=${2:-}
 valid_port "$port" || { err "$(L '端口须为 1–65535。' 'Use port 1–65535.')";return 1; }
 if [[ $host == *:* && $host != '['*']' ]];then host="[$host]";fi
 report_output reality_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --target "$host:$port" --tcp-only
}
port_diagnostics_engine(){
 python3 - "$BASE" "$CONF" "${LANGUAGE_CHOICE:-zh_CN}" <<'PY_PORT_DIAGNOSTICS'
# @include port_diagnostics.py
PY_PORT_DIAGNOSTICS
}
port_diagnostics_menu(){
 local choice host port
 if [[ $# == 0 || $1 == --menu ]];then
  prompt_options '端口连通性检测
1. 检测已安装节点（服务 / 监听 / 本机 TCP）
2. 检测远程 TCP 端口（本机 → 目标）
0. 返回' 'Port connectivity checks
1. Installed nodes (service / listener / local TCP)
2. Remote TCP port (this machine → target)
0. Back'
  [[ ${1:-} != --menu ]] || return 0
  prompt_read '> ' choice || return 0
 else choice=$1;fi
 case $choice in
  1)
   [[ ! -f $META ]] || check_owned || return 1
   xhttp_command guard || return 1
   report_output port_diagnostics_engine;;
  2)
   prompt_read "$(L '目标 VPS 的公网 IP / 域名：' 'Target VPS public IP / hostname: ')" host || return 0
   prompt_read "$(L '目标 TCP 端口：' 'Target TCP port: ')" port || return 0
   port_check_tcp "$host" "$port";;
  0) return 0;;
  *) return 1;;
 esac
}
