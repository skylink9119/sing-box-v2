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
 MENU_BACK=0
 printf '%s\n----------------------------------------------\n' "$GREEN"
 case $group in
  1) say '【节点安装】' '[Install nodes]';;
  2) say '【节点与订阅】' '[Nodes and subscriptions]';;
  3) say '【服务与日志】' '[Services and logs]';;
  4) say '【服务器与网络】' '[Server and network]';;
  5) say '【更新与备份】' '[Updates and backups]';;
  6) say '【设置与卸载】' '[Settings and uninstall]';;
 esac
 case $group in
  1)
   say ' 1. 安装 Reality + Vision' ' 1. Install Reality + Vision'
   say ' 2. 安装 Hysteria2' ' 2. Install Hysteria2'
   say ' 3. 安装双协议' ' 3. Install both protocols'
   say ' 4. Argo 临时 / 固定隧道管理' ' 4. Argo Quick / Named Tunnel controls'
   say ' 5. 节点参数与协议增删' ' 5. Node settings and protocol changes'
   say ' 6. 受限网络部署（Argo / IPv6 / NAT）' ' 6. Restricted networks (Argo / IPv6 / NAT)'
   say ' 7. 节点安装前检测（不安装）' ' 7. Node installation checks (no installation)'
   ;;
  2)
   say ' 1. 查看节点与各客户端格式' ' 1. View nodes and client formats'
   say ' 2. 导出本地订阅' ' 2. Export local subscriptions'
   say ' 3. 自定义节点名称' ' 3. Customize node names'
   say ' 4. 小火箭节点二维码' ' 4. Shadowrocket node QR codes'
   say ' 5. 用户数量、流量与有效期管理' ' 5. Account limits, traffic quotas and expiry'
   say ' 6. HTTPS 个人在线订阅' ' 6. Personal HTTPS subscriptions'
   say ' 7. 查看节点参数（注意保密）' ' 7. View node parameters (keep private)'
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
   say ' 7. 进程、内存与负载' ' 7. Processes, memory and load'
   say ' 8. 流媒体 / 回程 / 测速' ' 8. Media / routes / speed tests'
   say ' 9. WARP 出站与分流' ' 9. WARP egress and routing'
   say '10. 住宅落地 / VPS 中转' '10. Residential landing / VPS relay'
   say '11. HAProxy TCP 透传' '11. HAProxy TCP passthrough'
   say '12. Reality 握手网站检测' '12. Reality handshake target checks'
   say '13. IPv6 备用入口' '13. IPv6 backup entry'
   ;;
  5)
   say ' 1. 手动更新 sing-box' ' 1. Update sing-box'
   say ' 2. 备份配置' ' 2. Back up configuration'
   say ' 3. 恢复配置' ' 3. Restore configuration'
   say ' 4. 检查 / 更新 SKYBYTE Manager 管理脚本' ' 4. Check / update SKYBYTE Manager script'
   say ' 5. HY2 证书检查与续签重载' ' 5. HY2 certificate checks and renewal reload'
   say ' 6. ACME 证书申请与续签' ' 6. ACME issuance and renewal'
   say ' 7. 备份管理与加密导出' ' 7. Backup management and encryption'
   ;;
  6)
   say ' 1. 切换语言' ' 1. Change language'
   say ' 2. 法律与隐私声明' ' 2. Legal and privacy notice'
   say ' 3. 卸载 SKYBYTE Manager / sing-box' ' 3. Uninstall SKYBYTE Manager / sing-box'
   say ' 4. 使用说明' ' 4. Usage guide'
   ;;
 esac
 say ' 0. 返回主菜单' ' 0. Back to main menu'
 printf -- '----------------------------------------------%s\n' "$RESET"
 prompt_read "$(L '请选择：' 'Select: ')" choice || return 1
 case "$group:$choice" in
  1:1) MAIN_ACTION=install_reality;;
  1:2) MAIN_ACTION=install_hy2;;
  1:3) MAIN_ACTION=install_dual;;
  1:4) MAIN_ACTION=argo;;
  1:5) MAIN_ACTION=settings;;
  1:6) MAIN_ACTION=rescue;;
  1:7) MAIN_ACTION=install_checks;;
  2:1) MAIN_ACTION=nodes;;
  2:2) MAIN_ACTION=subscription;;
  2:3) MAIN_ACTION=rename;;
  2:4) MAIN_ACTION=qr;;
  2:5) MAIN_ACTION=users;;
  2:6) MAIN_ACTION=online;;
  2:7) MAIN_ACTION=node_parameters;;
  3:1) MAIN_ACTION=service;;
  3:2) MAIN_ACTION=logs;;
  3:3) MAIN_ACTION=argo_status;;
  4:1) MAIN_ACTION=initialize;;
  4:2) MAIN_ACTION=firewall;;
  4:3) MAIN_ACTION=audit;;
  4:4) MAIN_ACTION=bbr;;
  4:5) MAIN_ACTION=hop;;
  4:6) MAIN_ACTION=traffic;;
  4:7) MAIN_ACTION=resources;;
  4:8) MAIN_ACTION=media;;
  4:9) MAIN_ACTION=warp;;
  4:10) MAIN_ACTION=relay;;
  4:11) MAIN_ACTION=haproxy;;
  4:12) MAIN_ACTION=reality;;
  4:13) MAIN_ACTION=ipv6;;
  5:1) MAIN_ACTION=update;;
  5:2) MAIN_ACTION=backup;;
  5:3) MAIN_ACTION=restore;;
  5:4) MAIN_ACTION=manager_update;;
  5:5) MAIN_ACTION=certificate;;
  5:6) MAIN_ACTION=acme;;
  5:7) MAIN_ACTION=backup_tools;;
  6:1) MAIN_ACTION=language;;
  6:2) MAIN_ACTION=notice;;
  6:3) MAIN_ACTION=uninstall;;
  6:4) MAIN_ACTION=help;;
  *:0) MENU_BACK=1; return 0;; *) err "$(L '无效选项' 'Invalid choice')";;
 esac
}
dispatch_action(){
 local action=$1;shift
 case $action in
 install_reality) install_protocol 1;; install_hy2) install_protocol 2;; install_dual) install_protocol 3;;
 argo) argo_manager "$@";; nodes) exports;; node_parameters) report_output node_parameters;; subscription) subscription;; rename) rename_node;; qr) shadowrocket_qr;; users) users_manager;;
 service) service_manager "$@";; logs) report_output journalctl -u sing-box -n 80 --no-pager;; argo_status) report_output argo_status;;
 initialize) initialize_server;; firewall) firewall "$@";; audit) report_output firewall_audit;; bbr) bbr;; hop) hop "$@";; traffic) traffic "$@";;
 media) media_check "$@";; warp) warp_menu "$@";; relay) relay_menu "$@";; haproxy) haproxy_menu "$@";;
 ipv6) ipv6_menu "$@";;
 reality) reality_menu "$@";;
 install_checks) installation_check_menu "$@";;
 rescue) rescue_menu "$@";;
 manager_update) manager_update;; certificate) certificate_menu "$@";; resources) report_output resource_info;;
 update) core_versions "$@";; settings) node_settings "$@";; online) online_menu "$@";; acme) acme_menu "$@";; backup_tools) backup_tools "$@";; help) usage_help;; backup) backup;; restore) restore;;
 language) select_language && startup_info;; notice) notice;; uninstall) uninstall_manager;;
 esac
}
run_menu_action(){
 # Only a selected operation owns the lock. Never hold it while a menu waits.
 MENU_ACTION_STATUS=1
 if ! flock -n 9;then err "$(L '其他管理任务正在运行，请稍后重试' 'Another management task is running; retry shortly')";return 0;fi
 set +e
 ( set -Eeuo pipefail; trap action_failed ERR; "$@" )
 MENU_ACTION_STATUS=$?
 set -e
 flock -u 9
 if [[ -n ${SKYBYTE_SESSION_FILE:-} && -s $SKYBYTE_SESSION_FILE ]];then IFS= read -r SKYBYTE_ASSET_DIR < "$SKYBYTE_SESSION_FILE";export SKYBYTE_ASSET_DIR;fi
 load_language
}
run_submenu(){
 local handler=$1 choice
 while :;do
  # Rendering/selection runs in the controller, outside the operation subshell.
  "$handler" --menu || { action_failed; return 0; }
  say '操作后留在此菜单；0 返回上一层。' 'Stay in this menu after each operation; 0 returns one level.'
  prompt_read '> ' choice || return 0
  [[ $choice != 0 ]] || return 0
  # Enter child menus before taking a lock, so nested idle menus also release it.
  case "$handler:$choice" in
   warp_menu:6) run_submenu warp_rules_menu; continue;;
   warp_menu:8) run_submenu media_check; continue;;
  esac
  run_menu_action "$handler" "$choice"
 done
}
navigation_action(){
 case $1 in
  media) run_submenu media_check;;
  firewall) run_submenu firewall;; service) run_submenu service_manager;;
  traffic) run_submenu traffic;; argo) run_submenu argo_manager;;
  settings) run_submenu node_settings;; certificate) run_submenu certificate_menu;;
  acme) run_submenu acme_menu;; online) run_submenu online_menu;;
  rescue) run_submenu rescue_menu;; warp) run_submenu warp_menu;;
  relay) run_submenu relay_menu;; haproxy) run_submenu haproxy_menu;;
  ipv6) run_submenu ipv6_menu;;
  reality) run_submenu reality_menu;;
  install_checks) run_submenu installation_check_menu;;
  hop) run_submenu hop;; update) run_submenu core_versions;;
  backup_tools) run_submenu backup_tools;; users) users_manager;;
  *) run_menu_action dispatch_action "$1";;
 esac
}
main() (
 need_root; require_cmd flock
 local group='' selected MENU_BACK=0 MENU_ACTION_STATUS=0 SKYBYTE_SESSION_FILE
 SKYBYTE_SESSION_FILE=$(mktemp "$BASE/.session.XXXXXX") || return 1
 trap 'rm -f -- "$SKYBYTE_SESSION_FILE"' EXIT
 retire_auto_update || return 1
 startup_info
 # An idle main menu must not hold off certificate renewal.
 flock -u 9
 while :; do
 if [[ -z $group ]];then
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
  say ' a. 节点安装' ' a. Install nodes'
  say ' b. 节点与订阅' ' b. Nodes and subscriptions'
  say ' c. 服务与日志' ' c. Services and logs'
  say ' d. 服务器与网络' ' d. Server and network'
  say ' e. 更新与备份' ' e. Updates and backups'
  say ' f. 设置与卸载' ' f. Settings and uninstall'
  say ' g. 用户与配额管理' ' g. Users and quotas'
  report_output users_summary
  printf '%s' "$GREEN"
  say ' q. 退出' ' q. Exit'
  printf '%s' "$RESET"
  printf '%sYouTube: %s%s\n' "$CYAN" "$YOUTUBE" "$RESET"
  printf '%s%s%s\n' "$CYAN" "$(L '如果这个脚本对你有帮助，欢迎订阅我的 YouTube 频道，支持 SKYBYTE 持续更新！' "If you find this script helpful, please subscribe to my YouTube channel and support SKYBYTE's continued development!")" "$RESET"
  prompt_read "$(L '请选择（字母）：' 'Select (letter): ')" selected || return 0
  # Numeric aliases retain compatibility with previous releases.
  case $selected in
   a|A|1) group=1;; b|B|2) group=2;; c|C|3) group=3;; d|D|4) group=4;;
   e|E|5) group=5;; f|F|6) group=6;; g|G|7) group=7;;
   q|Q|0) return 0;; *) err "$(L '无效选项' 'Invalid choice')";continue;;
  esac
 fi
  if [[ $group == 7 ]];then MAIN_ACTION=users;group=''
  else sub_menu "$group" || return 0; [[ $MENU_BACK != 1 ]] || { group='';continue; };fi
  [[ -n $MAIN_ACTION ]] || continue
  navigation_action "$MAIN_ACTION"
  if [[ $MAIN_ACTION == uninstall && $MENU_ACTION_STATUS == 0 && ! -e $META ]]; then return 0; fi
  if [[ $MAIN_ACTION == manager_update && $MENU_ACTION_STATUS == 0 && -f $MANAGER_LIB ]] && ! grep -Fxq "MANAGER_VERSION=$MANAGER_VERSION" "$MANAGER_LIB"; then rm -f -- "$SKYBYTE_SESSION_FILE";exec 9>&-; exec bash "$MANAGER_LIB"; fi
 done
)

bootstrap(){
 need_root
 if ! command -v python3 >/dev/null || ! command -v flock >/dev/null;then apt_install python3 util-linux ca-certificates || return 1;fi
 require_cmd flock || return 1
 local directory
 for directory in "$BASE" "$REPORT" "$BACKUP";do
  [[ ! -L $directory && ( ! -e $directory || -d $directory ) ]] || { err "$(L '管理目录异常，拒绝写入' 'Unsafe manager directory; refusing writes')";return 1; }
 done
 [[ ! -L $LANG_FILE && ( ! -e $LANG_FILE || -f $LANG_FILE ) && ! -L $LOCK && ( ! -e $LOCK || -f $LOCK ) ]] || { err "$(L '语言或锁文件异常，拒绝写入' 'Language/lock file is unsafe; refusing writes')";return 1; }
 mkdir -p "$BASE" "$REPORT" "$BACKUP"; chmod 700 "$BASE" "$REPORT" "$BACKUP"
 exec 9>"$LOCK"; flock -n 9 || { err "$(L '其他管理任务正在运行' 'Another manager is running')"; return 1; }
 if [[ -z ${1:-} ]];then
  manager_shortcut_install || warn "$(L 'sb 快捷入口注册失败，已保留原有文件；可继续使用当前脚本。' 'Could not register sb shortcut; existing files retained. Current script remains usable.')"
 fi
 load_language
 if [[ -z $LANGUAGE_CHOICE ]]; then
  if [[ ${1:-} == --auto-update || ${1:-} == --certificate-check || ${1:-} == --certificate-reload || ${1:-} == --acme-renew || ${1:-} == --notice ]]; then LANGUAGE_CHOICE=en_US; else select_language || return 1; fi
 fi
 export LANGUAGE_CHOICE
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
 case ${1:-} in
  --help|-h) load_language;usage_help;exit 0;;
  --self-check) manager_self_check; exit $?;;
  --subscription-serve) need_root;online_guard && online_engine serve;exit $?;;
  --subscription-export) need_root;[[ $# == 2 ]] || exit 1;require_cmd flock || exit 1;exec 9>"$LOCK";flock -s -w 10 9 || exit 1;online_guard && users_guard && users_export "$2" >/dev/null;exit $?;;
  --users-watch) need_root; load_language; LANGUAGE_CHOICE=${LANGUAGE_CHOICE:-en_US}; users_engine watch; exit $?;;
  --argo-run) need_root; load_language; LANGUAGE_CHOICE=${LANGUAGE_CHOICE:-en_US}; argo_run; exit $?;;
  --argo-export) need_root; load_language; LANGUAGE_CHOICE=${LANGUAGE_CHOICE:-en_US}; exports; exit $?;;
 esac
 bootstrap "${1:-}" || exit 1
 case "${1:-}" in --acme-renew) acme_renew;; --auto-update) update_auto;; --certificate-check) certificate_check;; --certificate-reload) certificate_reload;; --notice) notice;; *) main;; esac
fi
