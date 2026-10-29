online_engine(){
 local -a command=(python3)
 [[ ${1:-} != serve ]] || command=(exec python3)
 "${command[@]}" - "$BASE" "$MANAGER_BIN" "$@" <<'PY_ONLINE'
# @include online.py
PY_ONLINE
}
online_guard(){
 local unit=$SYSTEMD_DIR/skybyte-subscriptions.service
 [[ ! -L $BASE/subscriptions.json ]] || return 1
 if [[ -e $unit || -L $unit ]];then
  [[ ! -L $unit ]] && grep -Fxq 'Description=SKYBYTE managed HTTPS subscriptions' "$unit" && grep -Fxq "ExecStart=/bin/bash $MANAGER_BIN --subscription-serve" "$unit" || return 1
 fi
 online_engine guard
}
online_setup(){
 check_owned && users_guard setup && online_guard || return 1
 local host port cert key
 [[ ! -e $BASE/subscriptions.json ]] || { err "$(L '订阅服务已配置，请使用状态、重载或停用' 'Subscription service configured; use status/reload/disable')";return 1; }
 prompt_read "$(L '订阅域名（DNS指向本机）：' 'Subscription hostname (DNS points here): ')" host || return 0
 prompt_read "$(L 'HTTPS 端口 [8443]：' 'HTTPS port [8443]: ')" port || return 0;port=${port:-8443}
 valid_port "$port" && ((10#$port>=1024)) || return 1
 haproxy_engine check_port "$port" || return 1
 if ss -H -ltn "( sport = :$port )" | grep -q .;then err "$(L '端口已占用' 'Port occupied')";return 1;fi
 prompt_read "$(L '可信 TLS 完整证书路径（回车用托管 ACME）：' 'Trusted TLS fullchain (Enter for managed ACME): ')" cert || return 0
 prompt_read "$(L 'TLS 私钥路径（回车用托管 ACME）：' 'TLS private key (Enter for managed ACME): ')" key || return 0
 cert=${cert:-$BASE/acme/config/live/skybyte/fullchain.pem};key=${key:-$BASE/acme/config/live/skybyte/privkey.pem}
 validate_certificate "$cert" "$key" "$host" || return 1
 if [[ $(openssl x509 -in "$cert" -noout -issuer -nameopt RFC2253) == "issuer=$(openssl x509 -in "$cert" -noout -subject -nameopt RFC2253 | sed 's/^subject=//')" ]];then
  err "$(L '在线订阅需要客户端信任的域名证书；请先申请 ACME，拒绝默认使用自签名' 'Online subscriptions require a client-trusted domain certificate; issue ACME first; self-signed is not used by default')";return 1
 fi
 online_chain_check "$cert" || { err "$(L '证书链未通过系统信任验证' 'Certificate chain did not pass system trust validation')";return 1; }
 confirm "$(L '开启公开 HTTPS 服务，仅通过独立 Token 返回个人客户端配置？' 'Enable public HTTPS delivery of personal client configs through independent tokens?')" || return 0
 [[ $SCRIPT_PATH -ef $MANAGER_BIN ]] || command install -m 700 "$SCRIPT_PATH" "$MANAGER_BIN" || return 1
 online_engine init "$host" "$port" "$cert" "$key" || return 1
 cat > "$SYSTEMD_DIR/skybyte-subscriptions.service" <<UNIT
[Unit]
Description=SKYBYTE managed HTTPS subscriptions
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=/bin/bash $MANAGER_BIN --subscription-serve
Restart=on-failure
RestartSec=5
KillMode=mixed
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
 if ! systemctl daemon-reload || ! systemctl enable --now skybyte-subscriptions.service || ! { sleep 2;systemctl is-active --quiet skybyte-subscriptions.service; };then
  systemctl disable --now skybyte-subscriptions.service || :;rm -f "$SYSTEMD_DIR/skybyte-subscriptions.service" "$BASE/subscriptions.json";systemctl daemon-reload || :;return 1
 fi
 if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active';then ufw allow "$port/tcp" || return 1;fi
 say "请在云防火墙放行 TCP ${port}。" "Allow TCP $port in the provider firewall."
 ok "$(L 'HTTPS 订阅服务已开启；在用户菜单签发个人订阅' 'HTTPS subscriptions enabled; issue personal links in user management')"
}
online_reload(){
 online_guard || return 1
 [[ -f $BASE/subscriptions.json ]] || return 0
 local cert key host
 { IFS= read -r cert;IFS= read -r key;IFS= read -r host; } < <(python3 - "$BASE/subscriptions.json" <<'PY_ONLINE_TLS'
import json,sys
s=json.load(open(sys.argv[1]));print(s['cert']);print(s['key']);print(s['host'])
PY_ONLINE_TLS
 )
 validate_certificate "$cert" "$key" "$host" || return 1
 if systemctl is-active --quiet skybyte-subscriptions.service;then systemctl restart skybyte-subscriptions.service && systemctl is-active --quiet skybyte-subscriptions.service;fi
}
online_remove(){
 online_guard || return 1
 if [[ -f $SYSTEMD_DIR/skybyte-subscriptions.service ]];then systemctl disable --now skybyte-subscriptions.service || return 1;rm -f "$SYSTEMD_DIR/skybyte-subscriptions.service";fi
 if [[ -f $BASE/subscriptions.json ]] && python3 - "$BASE" <<'PY_SUB_OWNED_CERT'
import json,pathlib,sys
base=pathlib.Path(sys.argv[1]);s=json.loads((base/'subscriptions.json').read_text())
sys.exit(0 if s['cert']==str(base/'subscription-backup.crt') and s['key']==str(base/'subscription-backup.key') else 1)
PY_SUB_OWNED_CERT
 then
  rm -f "$BASE/subscription-backup.crt" "$BASE/subscription-backup.key"
 fi
 rm -f "$BASE/subscriptions.json"
}
online_user(){
 users_guard && online_guard || return 1
 [[ -f $BASE/subscriptions.json ]] || { err "$(L '请先在节点与订阅菜单配置 HTTPS 服务' 'Configure HTTPS delivery in Nodes/subscriptions first')";return 1; }
 local id choice
 users_engine list;prompt_read "$(L '用户 ID：' 'Account ID: ')" id || return 0
 prompt_options '1. 签发 / 重置独立 Token
2. 查看个人订阅
3. 撤销 Token
0. 返回' '1. Issue / rotate independent token
2. View personal links
3. Revoke token
0. Back'
 prompt_read '> ' choice || return 0
 case $choice in
  1) confirm "$(L '签发新 Token？旧订阅地址将立即失效。' 'Issue new token? Previous subscription URL becomes invalid.')" && { printf '%s' "$RED";online_engine issue "$id";local rc=$?;printf '%s' "$RESET";return "$rc"; };;
  2) printf '%s' "$RED";online_engine links "$id";local rc=$?;printf '%s' "$RESET";return "$rc";;
  3) confirm "$(L '撤销个人在线订阅地址？节点凭据不变。' 'Revoke personal online subscription URL? Node credentials stay unchanged.')" && online_engine revoke "$id";;
  0) return 0;;*) return 1;;
 esac
}
online_menu(){
 online_guard || return 1
 local choice
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 prompt_options '1. 配置 HTTPS 服务
2. 服务状态
3. 启动
4. 停止
5. 重载证书
6. 用户订阅 Token
0. 返回' '1. Configure HTTPS
2. Status
3. Start
4. Stop
5. Reload certificate
6. Account tokens
0. Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
 case $choice in
  1) online_setup;;2) systemctl --no-pager status skybyte-subscriptions.service || :;;
  3) [[ -f $BASE/subscriptions.json && -f $SYSTEMD_DIR/skybyte-subscriptions.service ]] && systemctl enable --now skybyte-subscriptions.service;;
  4) [[ ! -f $SYSTEMD_DIR/skybyte-subscriptions.service ]] || systemctl disable --now skybyte-subscriptions.service;;
  5) online_reload;;6) online_user;;0) return 0;;*) return 1;;
 esac
}

online_chain_check(){ openssl verify -purpose sslserver -untrusted "$1" "$1" >/dev/null 2>&1; }
auxiliary_restore_snapshot() (
 local path=$1 host cert key created=false aux_acme=false aux_online=false aux_unit=false aux_success=false
 trap auxiliary_restore_cleanup EXIT
 acme_guard && online_guard || return 1
 # Keep live certificate-account/DNS state and current tokens; only fill absent state.
 if [[ ! -e $BASE/acme-state.json && ! -e $BASE/acme && -f $path/acme-state.json && -d $path/acme ]];then
  [[ ! -L $path/acme ]] && grep -Fxq 'SKYBYTE ACME v1' "$path/acme/.skybyte-owner" || return 1
  aux_acme=true
  cp -a "$path/acme" "$BASE/acme" && cp "$path/acme-state.json" "$BASE/acme-state.json" || return 1
  acme_guard || return 1
 fi
 if [[ ! -e $BASE/subscriptions.json && -f $path/subscriptions.json ]];then
  for cert in subscription-backup.crt subscription-backup.key;do [[ -f $path/$cert && ! -L $path/$cert && ! -e $BASE/$cert && ! -L $BASE/$cert ]] || return 1;done
  { IFS= read -r host;IFS= read -r cert;IFS= read -r key; } < <(python3 - "$path/subscriptions.json" <<'PY_SUB_RESTORE'
import json,sys
s=json.load(open(sys.argv[1]));assert s['owner']=='SKYBYTE HTTPS subscriptions v1';print(s['host']);print(s['cert']);print(s['key'])
PY_SUB_RESTORE
 )
  [[ $cert == "$BASE/subscription-backup.crt" && $key == "$BASE/subscription-backup.key" ]] || return 1
  validate_certificate "$path/subscription-backup.crt" "$path/subscription-backup.key" "$host" && online_chain_check "$path/subscription-backup.crt" || return 1
  aux_online=true
  cp "$path/subscription-backup.crt" "$cert" && cp "$path/subscription-backup.key" "$key" && cp "$path/subscriptions.json" "$BASE/subscriptions.json" || return 1
  chmod 600 "$cert" "$key" "$BASE/subscriptions.json";created=true
  if [[ -f $path/subscriptions.unit ]];then
   grep -Fxq 'Description=SKYBYTE managed HTTPS subscriptions' "$path/subscriptions.unit" && grep -Fxq "ExecStart=/bin/bash $MANAGER_BIN --subscription-serve" "$path/subscriptions.unit" || return 1
   users_guard setup || return 1
   [[ $SCRIPT_PATH -ef $MANAGER_BIN ]] || command install -m 700 "$SCRIPT_PATH" "$MANAGER_BIN" || return 1
   aux_unit=true
   cp "$path/subscriptions.unit" "$SYSTEMD_DIR/skybyte-subscriptions.service" || return 1
   online_guard && systemctl daemon-reload || return 1
   if [[ -f $path/subscriptions.active && $(cat "$path/subscriptions.active") == true ]];then systemctl enable --now skybyte-subscriptions.service && systemctl is-active --quiet skybyte-subscriptions.service || return 1;fi
  fi
 fi
 if [[ $created == true ]];then say '已恢复缺失的 HTTPS订阅；现有Token未覆盖。ACME自动续签需重新启用并确认关联路径。' 'Missing HTTPS subscriptions restored; existing tokens preserved. Re-enable ACME renewal after checking path association.';fi
 aux_success=true
)
auxiliary_restore_cleanup(){
 [[ ${aux_success:-false} != true ]] || return 0
 if [[ ${aux_unit:-false} == true ]];then systemctl disable --now skybyte-subscriptions.service || :;rm -f "$SYSTEMD_DIR/skybyte-subscriptions.service";systemctl daemon-reload || :;fi
 if [[ ${aux_online:-false} == true ]];then rm -f "$BASE/subscriptions.json" "$BASE/subscription-backup.crt" "$BASE/subscription-backup.key";fi
 if [[ ${aux_acme:-false} == true ]];then rm -f "$BASE/acme-state.json";rm -rf "$BASE/acme";fi
}
