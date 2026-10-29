users_engine(){
 local -a users_python=(python3)
 if [[ ${1:-} == watch ]]; then users_python=(exec python3); fi
 "${users_python[@]}" - "$BASE" "$CONF" "$META" "$BIN" "${LANGUAGE_CHOICE:-zh_CN}" "$@" <<'PY_USERS'
# @include users.py

PY_USERS
}
# Quota users run isolated direct Reality/HY2 cores, so their totals are per account.
users_guard(){
 local unit=skybyte-users.service file
 if [[ -e $SYSTEMD_DIR/$unit || -L $SYSTEMD_DIR/$unit ]]; then
  if [[ -L $SYSTEMD_DIR/$unit ]] || ! grep -Fxq 'Description=SKYBYTE managed user quota supervisor' "$SYSTEMD_DIR/$unit" || ! grep -Fxq "ExecStart=/bin/bash $MANAGER_BIN --users-watch" "$SYSTEMD_DIR/$unit"; then err "$(L '用户服务归属异常' 'User service ownership mismatch')"; return 1; fi
 fi
 for file in users.json users users.lock users-worker.lock; do
  [[ ! -L $BASE/$file ]] || { err "$(L '用户文件是符号链接，拒绝修改' 'User file is a symlink; refusing changes')"; return 1; }
 done
 if [[ ( -f $BASE/users.json || ${1:-} == setup ) && ( -e $MANAGER_BIN || -L $MANAGER_BIN ) ]]; then
  if [[ -L $MANAGER_BIN ]] || ! grep -q '^# SKYBYTE Manager V2.1 community manager;' "$MANAGER_BIN"; then err "$(L '管理脚本归属异常' 'Manager executable ownership mismatch')"; return 1; fi
 fi
 if [[ -f $BASE/users.json ]]; then users_engine guard || return 1; fi
}
users_setup_service(){
 users_guard setup || return 1
 if [[ ! $SCRIPT_PATH -ef $MANAGER_BIN ]]; then command install -m 700 "$SCRIPT_PATH" "$MANAGER_BIN" || return 1; fi
 cat > "$SYSTEMD_DIR/skybyte-users.service" <<EOF
[Unit]
Description=SKYBYTE managed user quota supervisor
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/bin/bash $MANAGER_BIN --users-watch
Restart=on-failure
RestartSec=5
KillMode=mixed
TimeoutStopSec=30
LimitNOFILE=1048576
UMask=0077
[Install]
WantedBy=multi-user.target
EOF
 systemctl daemon-reload
}
users_firewall_allow(){
 [[ -f $BASE/users.json ]] || return 0
 users_guard || return 1
 local rules rule
 rules=$(users_engine firewall_rules "${1:-}") || return 1
 while IFS= read -r rule; do [[ -z $rule ]] || ufw allow "$rule" || return 1; done <<<"$rules"
}
users_start(){
 users_guard || return 1
 if ! python3 - "$BASE/users.json" <<'PY'
import json,sys
sys.exit(0 if json.load(open(sys.argv[1])).get('supervisor_enabled',True) else 1)
PY
 then return 0; fi
 users_setup_service && users_engine validate "$BIN" && systemctl enable --now skybyte-users.service
}
users_stop(){ users_guard || return 1; if [[ -f $SYSTEMD_DIR/skybyte-users.service ]]; then systemctl stop skybyte-users.service; fi; }
users_restore_snapshot(){
 local path=$1 limit
 users_guard && users_stop || return 1
 if [[ -f $path/users.json ]]; then
  if [[ ! -f $BASE/users.json ]]; then
   limit=$(python3 - "$path/users.json" <<'PY'
import json,sys
print(json.load(open(sys.argv[1]))['limit'])
PY
 ) || return 1
   users_engine init "$limit" || return 1
  fi
  users_engine restore "$path" || return 1
  users_start || return 1
 elif [[ -f $BASE/users.json ]]; then users_start || return 1; fi
}
users_remove(){
 users_guard || return 1
 [[ -f $BASE/users.json || -f $SYSTEMD_DIR/skybyte-users.service ]] || return 0
 if [[ -f $SYSTEMD_DIR/skybyte-users.service ]]; then systemctl disable --now skybyte-users.service || return 1; rm -f "$SYSTEMD_DIR/skybyte-users.service"; fi
 if [[ -f $BASE/users.json ]]; then users_engine cleanup || return 1; fi
 rm -f "$BASE/users.lock" "$BASE/users-worker.lock"
}
users_export(){
 local id=$1 path
 local BASE=$BASE META=$META CONF=$CONF
 path=$(users_engine export "$id") || return 1
 BASE=$path; META=$path/state.json; CONF=$path/server.json; exports
}
users_qr(){
 local id=$1 path
 local BASE=$BASE META=$META CONF=$CONF
 path=$(users_engine export "$id") || return 1
 BASE=$path; META=$path/state.json; CONF=$path/server.json; shadowrocket_qr
}
users_manager(){ run_submenu users_menu_step; }
users_menu_step(){
 check_owned && users_guard || return 1
 if ! python3 - "$CONF" <<'PY_USERS_PROTOCOLS'
import json,sys
sys.exit(0 if any(i.get('type') in ('vless','hysteria2') for i in json.load(open(sys.argv[1])).get('inbounds',[])) else 1)
PY_USERS_PROTOCOLS
 then warn "$(L 'Argo 单独部署不支持配额用户；请先安装 Reality 或 HY2 直连节点。' 'Quota accounts require a direct Reality or HY2 node; standalone Argo alone is unsupported.')";return 1;fi
 warn "$(L '仅新建的受限账户执行人数、流量和到期限制。原管理员节点及 Argo 不受此配额管理。每人独立进程/端口；请放行云防火墙对应端口。' 'Limits apply only to new managed accounts. Existing admin nodes and Argo are outside these quotas. Each account uses its own process/port; allow those provider firewall ports.')"
 local choice max name quota days id action port snap
 if [[ $# == 0 || $1 == --menu ]]; then
  printf '%s' "$GREEN"
  say '【账户与配额】' '[Accounts and quotas]'
  prompt_options '1. 初始化用户管理
2. 添加用户
3. 查看用量
4. 修改流量额度' '1. Initialize
2. Add account
3. Usage
4. Change quota'
  prompt_options '5. 启用/禁用用户
6. 删除用户
7. 重置流量
8. 设置人数上限' '5. Enable/disable
6. Delete
7. Reset usage
8. Set account limit'
  say '【节点与服务】' '[Nodes and services]'
  prompt_options '9. 用户节点与二维码
10. 服务状态
11. 启动用户服务
12. 停止用户服务' '9. User exports/QR
10. Status
11. Start supervisor
12. Stop supervisor'
  say '【有效期与诊断】' '[Validity and diagnostics]'
  prompt_options '13. 修改有效期
14. 用户故障诊断
15. 资源占用
16. 个人在线订阅
0. 返回' '13. Change validity
14. User diagnostics
15. Resources
16. Personal subscriptions
0. Back'
  printf '%s' "$RESET"
  [[ ${1:-} != --menu ]] || return 0
  prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
  [[ $choice != 0 ]] || return 0
  if [[ $choice != 1 && ! -f $BASE/users.json ]]; then err "$(L '请先初始化用户管理' 'Initialize user management first')"; return 0; fi
  case $choice in
   1)
    [[ ! -f $BASE/users.json ]] || { err "$(L '用户管理已存在，拒绝覆盖' 'User management exists; refusing overwrite')"; return 0; }
    prompt_read "$(L '最多用户数 [10]（1-100）：' 'Maximum accounts [10] (1-100): ')" max || return 0
    max=${max:-10}
    if ! valid_port "$max" || ! (( 10#$max<=100 )); then err "$(L '账户上限须为1至100' 'Account limit must be 1-100')"; return 1; fi
    users_guard setup || return 1
    confirm "$(L '初始化独立用户服务？已有节点将保留。' 'Initialize isolated user services? Existing nodes remain.')" || return 0
    snap=$(backup) || return 1
    users_engine init "$max" && users_start || return 1
    say "初始化完成；备份：$snap" "Initialized; backup: $snap";;
   2)
    prompt_read "$(L '用户名：' 'User name: ')" name || return 0
    prompt_read "$(L '总流量 GiB [100]：' 'Total quota GiB [100]: ')" quota || return 0
    prompt_read "$(L '有效天数 [30]：' 'Validity days [30]: ')" days || return 0
    id=$(users_engine add "$name" "${quota:-100}" "${days:-30}") || return 1
    port=$(python3 - "$BASE/users.json" "$id" <<'PY'
import json,sys
print(next(u['port'] for u in json.load(open(sys.argv[1]))['users'] if u['id']==sys.argv[2]))
PY
 ) || return 1
    if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active'; then
     users_firewall_allow "$id" || return 1
    fi
    users_start || return 1
    ok "$(L '已创建用户 ID：' 'Created account ID: ')$id"
    warn "$(L "请在云防火墙放行节点端口 ${port}；控制 API 仅监听本机，不应公开。" "Allow node port $port in provider firewall; the controller API stays loopback-only.")"
    users_export "$id";;
   3) users_engine list;;
   4)
    users_engine list
    prompt_read "$(L '用户 ID：' 'Account ID: ')" id || return 0
    prompt_read "$(L '总流量 GiB：' 'Total quota GiB: ')" quota || return 0
    confirm "$(L '只修改流量额度，保留到期时间和累计用量？' 'Change quota only, retaining expiry and usage?')" || return 0
    users_engine quota "$id" "$quota";;
   5)
    users_engine list
    prompt_read "$(L '用户 ID：' 'Account ID: ')" id || return 0
    prompt_read "$(L '1 启用  2 禁用：' '1 Enable  2 Disable: ')" action || return 0
    case $action in 1) users_engine enable "$id" || return 1; if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active'; then users_firewall_allow "$id"; fi;; 2) users_engine disable "$id";; *) return 1;; esac;;
   6|7)
    users_engine list
    prompt_read "$(L '用户 ID：' 'Account ID: ')" id || return 0
    confirm "$(L '确认删除用户或重置其累计流量？' 'Confirm deleting the account or resetting its cumulative usage?')" || return 0
    if [[ $choice == 6 ]]; then users_engine delete "$id"; else users_engine reset "$id"; fi;;
   8)
    prompt_read "$(L '最多用户数（1-100）：' 'Maximum accounts (1-100): ')" max || return 0
    users_engine limit "$max";;
   9)
    users_engine list
    prompt_read "$(L '用户 ID：' 'Account ID: ')" id || return 0
    users_export "$id" && users_qr "$id";;
   10) systemctl --no-pager status skybyte-users.service || :; users_engine list;;
   11) users_engine service on && users_start;;
   13)
    users_engine list
    prompt_read "$(L '用户 ID：' 'Account ID: ')" id || return 0
    prompt_read "$(L '从现在起有效天数：' 'Validity days from now: ')" days || return 0
    confirm "$(L '从现在重新设置有效期，保留额度和累计用量？' 'Set validity from now, retaining quota and usage?')" || return 0
    users_engine validity "$id" "$days";;
   14) users_diagnostics;;
   15) resource_info;;
   16) online_user;;
   12) if confirm "$(L '停止全部受限用户节点？' 'Stop all quota-managed user nodes?')"; then users_engine service off && users_stop; fi;;
   *) err "$(L '无效选项' 'Invalid selection')";;
  esac
}
