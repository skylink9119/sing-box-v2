# shellcheck shell=bash
ipv6_engine(){
 python3 - sing-box "$BASE" "$CONF" "$@" <<'PY_IPV6'
# @include ipv6.py
import sys
try:ipv6_cli(*sys.argv[1:])
except (ValueError,OSError,KeyError,subprocess.SubprocessError) as error:
 print(str(error),file=sys.stderr);sys.exit(1)
PY_IPV6
}
ipv6_menu(){
 local choice candidates selected
 if [[ $# == 0 || $1 == --menu ]];then
  prompt_options 'IPv6 备用入口
1. 查看 IPv6 备用状态
2. 检测并启用 IPv6 备用入口
3. 移除 IPv6 备用入口（保留原节点）
0. 返回' 'IPv6 backup entry
1. Show IPv6 backup status
2. Detect and enable IPv6 backup
3. Remove IPv6 backup (keep original nodes)
0. Back'
  [[ ${1:-} != --menu ]] || return 0
  prompt_read '> ' choice || return 0
 else choice=$1;fi
 configuration_guard && users_guard || return 1
 case $choice in
  1) report_output ipv6_engine status;;
  2)
   candidates=$(ipv6_engine detect) || return 1
   say '本机可用公网 IPv6：' 'Available native IPv6:'
   printf '%s\n' "$candidates"
   prompt_read "$(L '备用 IPv6（回车使用第一个）：' 'Backup IPv6 (Enter uses first): ')" selected || return 0
   selected=${selected:-${candidates%%$'\n'*}}
   ipv6_engine check "$selected" || return 1
   warn "$(L '保留原地址、UUID、密钥、端口和 SNI，主节点及受限用户节点启用双栈并额外导出 IPv6 备用节点；Argo 保持不变。客户端网络必须支持 IPv6，请放行云防火墙的实际 IPv6 TCP/UDP 端口。节点参数及链接保存在当前 VPS，请勿公开。' 'Keeps original addresses, UUIDs, keys, ports and SNI. Administrator and quota-managed nodes gain dual-stack IPv6 backups; Argo is preserved. Client IPv6 and provider IPv6 TCP/UDP rules are required. Exports remain private on this VPS.')"
   confirm "$(L '启用 IPv6 备用入口并重载正在运行的节点？' 'Enable IPv6 backup and reload running nodes?')" || return 0
   configuration_apply ipv6 "$selected" || return 1
   report_output ipv6_engine status
   say '重新导入节点后选择“IPv6备用”。已验证运行中主节点的本地监听；公网连通请从有 IPv6 的客户端测试。停止的服务保持停止。' 'Re-import and select the IPv6 backup node. Running administrator listeners checked locally; test public ingress from an IPv6 client. Stopped services remain stopped.';;
  3)
   confirm "$(L '移除 IPv6 备用链接并恢复启用前监听？原节点凭据保持不变。' 'Remove IPv6 backup links and restore previous listeners, keeping credentials?')" || return 0
   configuration_apply ipv6 off || return 1
   report_output ipv6_engine status;;
  0) return 0;;*) return 1;;
 esac
}
