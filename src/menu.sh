manager_self_check(){
 python3 - "$SCRIPT_PATH" <<'PY_SELF_CHECK'
import pathlib,re,sys
s=pathlib.Path(sys.argv[1]).read_text()
for m in re.finditer(r"<<'(PY[^']*)'\n(.*?)\n\1(?:\n|$)",s,re.S):compile(m[2],m[1],'exec')
m=re.search(r'^MANAGER_VERSION=([0-9]+\.[0-9]+\.[0-9]+)$',s,re.M);assert m
assert '# SKYBYTE Manager V2.1 community manager;' in s
print(m[1])
PY_SELF_CHECK
}
action_failed(){ err "$(L '操作失败；请检查上面的输出' 'Operation failed; inspect the output above')"; }
sub_menu(){
 local group=$1 choice
 MAIN_ACTION=""
 printf '%s\n----------------------------------------------\n' "$GREEN"
 case $group in
  1)
   say ' 1. 安装 Reality + Vision' ' 1. Install Reality + Vision'
   say ' 2. 安装 Hysteria2' ' 2. Install Hysteria2'
   say ' 3. 安装双协议' ' 3. Install both protocols'
   say ' 4. Argo 临时 / 固定隧道管理' ' 4. Argo Quick / Named Tunnel controls'
   ;;
  2)
   say ' 1. 查看节点与各客户端格式' ' 1. View nodes and client formats'
   say ' 2. 导出本地订阅' ' 2. Export local subscriptions'
   say ' 3. 自定义节点名称' ' 3. Customize node names'
   say ' 4. 小火箭节点二维码' ' 4. Shadowrocket node QR codes'
   say ' 5. 用户数量、流量与有效期管理' ' 5. Account limits, traffic quotas and expiry'
   ;;
  3)
   say ' 1. sing-box 状态与启停' ' 1. sing-box status and controls'
   say ' 2. 查看 sing-box 日志' ' 2. View sing-box logs'
   say ' 3. Argo 隧道状态' ' 3. Argo tunnel status'
   ;;
  4)
   say ' 1. 新服务器初始化' ' 1. Initialize new server'
   say ' 2. UFW 防火墙管理' ' 2. UFW controls'
   say ' 3. 检查防火墙规则' ' 3. Audit firewall rules'
   say ' 4. 启用 BBR + FQ' ' 4. Enable BBR + FQ'
   say ' 5. HY2 端口跳跃' ' 5. HY2 port hopping'
   say ' 6. VPS 流量统计（vnStat）' ' 6. VPS traffic (vnStat)'
   say ' 7. IP 信息' ' 7. IP information'
   say ' 8. 基础网络诊断' ' 8. Basic network checks'
   say ' 9. HY2 / 小火箭连接诊断' ' 9. HY2 / Shadowrocket checks'
   say '10. 进程、内存与负载' '10. Processes, memory and load'
   ;;
  5)
   say ' 1. 手动更新 sing-box' ' 1. Update sing-box'
   say ' 2. 每周自动更新' ' 2. Weekly automatic updates'
   say ' 3. 备份配置' ' 3. Back up configuration'
   say ' 4. 恢复配置' ' 4. Restore configuration'
   say ' 5. 检查 / 更新 SKYBYTE Manager 管理脚本' ' 5. Check / update SKYBYTE Manager script'
   say ' 6. HY2 证书检查与续签重载' ' 6. HY2 certificate checks and renewal reload'
   ;;
  6)
   say ' 1. 切换语言' ' 1. Change language'
   say ' 2. 法律与隐私声明' ' 2. Legal and privacy notice'
   say ' 3. 卸载 SKYBYTE Manager / sing-box' ' 3. Uninstall SKYBYTE Manager / sing-box'
   ;;
 esac
 say ' 0. 返回主菜单' ' 0. Back to main menu'
 printf -- '----------------------------------------------%s\n' "$RESET"
 read -r -p "$(L '请选择：' 'Select: ')" choice || return 1
 case "$group:$choice" in
  1:1) MAIN_ACTION=install_reality;;
  1:2) MAIN_ACTION=install_hy2;;
  1:3) MAIN_ACTION=install_dual;;
  1:4) MAIN_ACTION=argo;;
  2:1) MAIN_ACTION=nodes;;
  2:2) MAIN_ACTION=subscription;;
  2:3) MAIN_ACTION=rename;;
  2:4) MAIN_ACTION=qr;;
  2:5) MAIN_ACTION=users;;
  3:1) MAIN_ACTION=service;;
  3:2) MAIN_ACTION=logs;;
  3:3) MAIN_ACTION=argo_status;;
  4:1) MAIN_ACTION=initialize;;
  4:2) MAIN_ACTION=firewall;;
  4:3) MAIN_ACTION=audit;;
  4:4) MAIN_ACTION=bbr;;
  4:5) MAIN_ACTION=hop;;
  4:6) MAIN_ACTION=traffic;;
  4:7) MAIN_ACTION=ip;;
  4:8) MAIN_ACTION=network;;
  4:9) MAIN_ACTION=hy2_check;;
  4:10) MAIN_ACTION=resources;;
  5:1) MAIN_ACTION=update;;
  5:2) MAIN_ACTION=auto;;
  5:3) MAIN_ACTION=backup;;
  5:4) MAIN_ACTION=restore;;
  5:5) MAIN_ACTION=manager_update;;
  5:6) MAIN_ACTION=certificate;;
  6:1) MAIN_ACTION=language;;
  6:2) MAIN_ACTION=notice;;
  6:3) MAIN_ACTION=uninstall;;
  *:0) return 0;; *) err "$(L '无效选项' 'Invalid choice')";;
 esac
}
dispatch_action(){
 case $1 in
 install_reality) install_protocol 1;; install_hy2) install_protocol 2;; install_dual) install_protocol 3;;
 argo) argo_manager;; nodes) exports;; subscription) subscription;; rename) rename_node;; qr) shadowrocket_qr;; users) users_manager;;
 service) service_manager;; logs) journalctl -u sing-box -n 80 --no-pager;; argo_status) argo_status;;
 initialize) initialize_server;; firewall) firewall;; audit) firewall_audit;; bbr) bbr;; hop) hop;; traffic) traffic;;
 ip) ipcheck;; network) netcheck;; hy2_check) hy2_diagnostics;;
 manager_update) manager_update;; certificate) certificate_menu;; resources) resource_info;;
 update) update;; auto) configure_auto;; backup) backup;; restore) restore;;
 language) select_language && startup_info;; notice) notice;; uninstall) uninstall_manager;;
 esac
}
main(){
 need_root; require_cmd flock
 local group action_status
 startup_info
 while :; do
  printf '%s\n==============================================\n' "$CYAN"
  cat <<LOGO
   ███████╗██╗  ██╗██╗   ██╗██████╗ ██╗   ██╗████████╗███████╗
   ██╔════╝██║ ██╔╝╚██╗ ██╔╝██╔══██╗╚██╗ ██╔╝╚══██╔══╝██╔════╝
   ███████╗█████╔╝  ╚████╔╝ ██████╔╝ ╚████╔╝    ██║   █████╗
   ╚════██║██╔═██╗   ╚██╔╝  ██╔══██╗  ╚██╔╝     ██║   ██╔══╝
   ███████║██║  ██╗   ██║   ██████╔╝   ██║      ██║   ███████╗
   ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═════╝    ╚═╝      ╚═╝   ╚══════╝
                  SKYBYTE Manager v${MANAGER_VERSION}
                Reality · Hysteria2 · VPS
LOGO
  printf '==============================================%s\n' "$RESET"
  printf '%s' "$GREEN"
  say ' 1. 协议安装与 Argo 隧道' ' 1. Protocol installation and Argo tunnels'
  say ' 2. 节点与订阅' ' 2. Nodes and subscriptions'
  say ' 3. 服务与日志' ' 3. Services and logs'
  say ' 4. 服务器与网络' ' 4. Server and network'
  say ' 5. 更新与备份' ' 5. Updates and backups'
  say ' 6. 设置与卸载' ' 6. Settings and uninstall'
  say ' 7. 用户与配额管理' ' 7. Users and quotas'
  users_summary
  say ' 0. 退出' ' 0. Exit'
  printf '%s' "$RESET"
  printf '%sYouTube: %s%s\n' "$CYAN" "$YOUTUBE" "$RESET"
  read -r -p "$(L '请选择：' 'Select: ')" group || return 0
  [[ $group != 0 ]] || return 0
  case $group in 7) MAIN_ACTION=users;; 1|2|3|4|5|6) sub_menu "$group" || return 0;; *) err "$(L '无效选项' 'Invalid choice')"; continue;; esac
  [[ -n $MAIN_ACTION ]] || continue
  set +e
  ( set -Eeuo pipefail; trap action_failed ERR; dispatch_action "$MAIN_ACTION" )
  action_status=$?
  set -e
  if [[ $MAIN_ACTION == uninstall && $action_status == 0 && ! -e $META ]]; then return 0; fi
  if [[ $MAIN_ACTION == manager_update && $action_status == 0 && -f $MANAGER_LIB ]] && ! grep -Fxq "MANAGER_VERSION=$MANAGER_VERSION" "$MANAGER_LIB"; then exec 9>&-; exec bash "$MANAGER_LIB"; fi
  load_language
 done
}

bootstrap(){
 need_root
 require_cmd flock || return 1
 mkdir -p "$BASE" "$REPORT" "$BACKUP"; chmod 700 "$BASE" "$REPORT" "$BACKUP"
 exec 9>"$LOCK"; flock -n 9 || { err "$(L '其他管理任务正在运行' 'Another manager is running')"; return 1; }
 load_language
 if [[ -z $LANGUAGE_CHOICE ]]; then
  if [[ ${1:-} == --auto-update || ${1:-} == --certificate-check || ${1:-} == --certificate-reload || ${1:-} == --notice ]]; then LANGUAGE_CHOICE=en_US; else select_language || return 1; fi
 fi
 export LANGUAGE_CHOICE
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
 case ${1:-} in
  --self-check) manager_self_check; exit $?;;
  --users-watch) need_root; load_language; LANGUAGE_CHOICE=${LANGUAGE_CHOICE:-en_US}; users_engine watch; exit $?;;
  --argo-run) need_root; load_language; LANGUAGE_CHOICE=${LANGUAGE_CHOICE:-en_US}; argo_run; exit $?;;
  --argo-export) need_root; load_language; LANGUAGE_CHOICE=${LANGUAGE_CHOICE:-en_US}; exports; exit $?;;
 esac
 bootstrap "${1:-}" || exit 1
 case "${1:-}" in --auto-update) update_auto;; --certificate-check) certificate_check;; --certificate-reload) certificate_reload;; --notice) notice;; *) main;; esac
fi
