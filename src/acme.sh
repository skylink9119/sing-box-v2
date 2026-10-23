acme_guard(){
 local file unit
 for file in acme-state.json acme;do [[ ! -L $BASE/$file ]] || return 1;done
 if [[ -d $BASE/acme ]];then [[ -f $BASE/acme/.skybyte-owner && ! -L $BASE/acme/.skybyte-owner ]] && grep -Fxq 'SKYBYTE ACME v1' "$BASE/acme/.skybyte-owner" || return 1;fi
 for unit in skybyte-acme.service skybyte-acme.timer;do
  if [[ -e $SYSTEMD_DIR/$unit || -L $SYSTEMD_DIR/$unit ]];then
   [[ ! -L $SYSTEMD_DIR/$unit ]] && grep -Fxq 'Description=SKYBYTE managed ACME renewal' "$SYSTEMD_DIR/$unit" || return 1
   if [[ $unit == skybyte-acme.service ]];then grep -Fxq "ExecStart=/bin/bash $MANAGER_BIN --acme-renew" "$SYSTEMD_DIR/$unit" || return 1;fi
  fi
 done
 if [[ -f $BASE/acme-state.json ]];then python3 - "$BASE/acme-state.json" <<'PY_ACME_GUARD'
import json,re,sys
s=json.load(open(sys.argv[1]));assert s['owner']=='SKYBYTE ACME v1' and s['schema']==1 and s['method'] in ('http','cloudflare')
assert re.fullmatch(r'[a-zA-Z0-9.-]+',s['domain']) and '.' in s['domain']
PY_ACME_GUARD
 fi
}
acme_options(){
 # Keep Certbot's own state isolated; never operate on /etc/letsencrypt.
 ACME_ARGS=(--config-dir "$BASE/acme/config" --work-dir "$BASE/acme/work" --logs-dir "$BASE/acme/logs")
}
acme_issue(){
 need_root;acme_guard || return 1
 local domain email method token cert key
 [[ ! -e $BASE/acme-state.json && ! -e $BASE/acme ]] || { err "$(L '已有托管 ACME，请使用续签；拒绝覆盖账号和配置' 'Managed ACME exists; use renewal; refusing overwrite')";return 1; }
 prompt_read "$(L '证书域名：' 'Certificate domain: ')" domain || return 0
 [[ $domain =~ ^[a-zA-Z0-9.-]+$ && $domain == *.* && $domain != .* && $domain != *..* ]] || return 1
 prompt_read "$(L 'ACME 联系邮箱：' 'ACME contact email: ')" email || return 0
 [[ $email =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || return 1
 prompt_options '1 HTTP-01（域名指向本机，TCP80可达）  2 Cloudflare DNS-01' '1 HTTP-01 (domain points here; TCP80 reachable)  2 Cloudflare DNS-01'
 prompt_read '> ' method || return 0
 case $method in
  1) method=http; if ss -H -ltn '( sport = :80 )' | grep -q .;then err "$(L 'TCP80 已占用，保留现有服务；请选择 DNS 验证' 'TCP80 occupied; existing service preserved. Use DNS validation.')";return 1;fi;;
  2) method=cloudflare;; *) return 1;;
 esac
 say '申请公开证书会公开域名；请阅读并同意 CA 条款 https://letsencrypt.org/repository/ 。DNS Token 需仅授权对应区域 DNS 编辑。' 'Public issuance publishes the domain. Review CA terms: https://letsencrypt.org/repository/ . Scope DNS tokens to the target zone.'
 confirm "$(L '接受 CA 条款并申请证书？' 'Accept CA terms and request certificate?')" || return 0
 apt_install certbot || return 1
 if [[ $method == cloudflare ]];then apt_install python3-certbot-dns-cloudflare || return 1;fi
 mkdir -m 700 "$BASE/acme" || return 1
 printf 'SKYBYTE ACME v1\n' > "$BASE/acme/.skybyte-owner"
 acme_options
 local -a challenge=(--standalone)
 if [[ $method == cloudflare ]];then
  prompt_read "$(L 'Cloudflare DNS API Token（隐藏）：' 'Cloudflare DNS API Token (hidden): ')" token secret || return 1;echo
  [[ $token =~ ^[a-zA-Z0-9_-]{20,200}$ ]] || return 1
  printf 'dns_cloudflare_api_token = %s\n' "$token" > "$BASE/acme/cloudflare.ini";chmod 600 "$BASE/acme/cloudflare.ini";unset token
  challenge=(--dns-cloudflare --dns-cloudflare-credentials "$BASE/acme/cloudflare.ini" --dns-cloudflare-propagation-seconds 60)
 else
  warn "$(L '请确认域名 A/AAAA 记录正确，且 UFW 和云安全组允许 TCP80；脚本不会停止已有网站。' 'Verify domain A/AAAA records and allow TCP80 in UFW/provider rules; existing sites are not stopped.')"
  if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active';then ufw allow 80/tcp || return 1;fi
 fi
 if ! certbot certonly "${ACME_ARGS[@]}" "${challenge[@]}" --non-interactive --agree-tos --email "$email" --cert-name skybyte -d "$domain" > "$BASE/acme/last-issue.log" 2>&1;then
  chmod 600 "$BASE/acme/last-issue.log";err "$(L "申请失败；私密日志：$BASE/acme/last-issue.log。可选择清理失败申请后重试。" "Issuance failed; private log: $BASE/acme/last-issue.log. Clean failed attempt before retrying.")";return 1
 fi
 cert=$BASE/acme/config/live/skybyte/fullchain.pem;key=$BASE/acme/config/live/skybyte/privkey.pem
 validate_certificate "$cert" "$key" "$domain" || return 1
 python3 - "$BASE/acme-state.json" "$domain" "$method" <<'PY_ACME_STATE'
import json,os,sys,tempfile
fd,tmp=tempfile.mkstemp(dir=os.path.dirname(sys.argv[1]))
with os.fdopen(fd,'w') as f:json.dump({'owner':'SKYBYTE ACME v1','schema':1,'domain':sys.argv[2],'method':sys.argv[3]},f)
os.replace(tmp,sys.argv[1])
PY_ACME_STATE
 ok "$(L '证书申请成功' 'Certificate issued')"
 say "证书：${cert}；私钥请勿公开。" "Certificate: $cert; keep the key private."
 acme_use_hy2
}
acme_use_hy2(){
 acme_guard && [[ -f $BASE/acme-state.json ]] || return 1
 [[ -f $CONF ]] || return 0
 if ! protocol_port hysteria2 >/dev/null 2>&1;then say 'HY2 尚未安装；可在添加 HY2 或在线订阅时使用此证书。' 'HY2 is not installed; use this certificate when adding HY2 or online subscriptions.';return 0;fi
 local domain
 domain=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["domain"])' "$BASE/acme-state.json") || return 1
 if confirm "$(L '将托管证书用于 HY2，保留密码和用量？' 'Use managed certificate for HY2, preserving passwords and usage?')";then
  configuration_apply tls "$domain" "$BASE/acme/config/live/skybyte/fullchain.pem" "$BASE/acme/config/live/skybyte/privkey.pem" || return 1
  certificate_record "$(openssl x509 -in "$BASE/acme/config/live/skybyte/fullchain.pem" -noout -fingerprint -sha256)"
 fi
}
acme_renew(){
 acme_guard && [[ -f $BASE/acme-state.json ]] || return 1
 require_cmd certbot || return 1;acme_options
 certbot renew "${ACME_ARGS[@]}" --cert-name skybyte --non-interactive > "$BASE/acme/last-renew.log" 2>&1 || { err "$(L '续签失败，保留当前证书；检查私密日志' 'Renewal failed; current certificate retained; inspect private log')";return 1; }
 chmod 600 "$BASE/acme/last-renew.log"
 local domain cert=$BASE/acme/config/live/skybyte/fullchain.pem key=$BASE/acme/config/live/skybyte/privkey.pem
 domain=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["domain"])' "$BASE/acme-state.json") || return 1
 validate_certificate "$cert" "$key" "$domain" || return 1
 if [[ -f $CONF ]] && [[ $(state cert_path) == "$cert" ]];then certificate_check || return 1;fi
 if [[ -f $BASE/subscriptions.json ]];then online_reload || return 1;fi
}
acme_timer(){
 acme_guard && users_guard setup && [[ -f $BASE/acme-state.json ]] || return 1
 [[ $SCRIPT_PATH -ef $MANAGER_BIN ]] || command install -m 700 "$SCRIPT_PATH" "$MANAGER_BIN" || return 1
 cat > "$SYSTEMD_DIR/skybyte-acme.service" <<UNIT
[Unit]
Description=SKYBYTE managed ACME renewal
[Service]
Type=oneshot
ExecStart=/bin/bash $MANAGER_BIN --acme-renew
UMask=0077
UNIT
 cat > "$SYSTEMD_DIR/skybyte-acme.timer" <<'UNIT'
[Unit]
Description=SKYBYTE managed ACME renewal
[Timer]
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=1h
Persistent=true
[Install]
WantedBy=timers.target
UNIT
 if certificate_identity >/dev/null 2>&1;then certificate_check || return 1;fi
 systemctl daemon-reload && systemctl enable --now skybyte-acme.timer
}
acme_menu(){
 acme_guard || return 1
 local choice
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 prompt_options '1 申请域名证书  2 使用证书用于 HY2  3 手动续签  4 开启自动续签  5 关闭自动续签  6 清理未完成的申请  0 返回' '1 Issue domain certificate  2 Use for HY2  3 Renew  4 Enable auto-renew  5 Disable auto-renew  6 Clean failed issuance  0 Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
 case $choice in
  1) acme_issue;;2) acme_use_hy2;;3) acme_renew;;4) acme_timer;;
  5) [[ ! -f $SYSTEMD_DIR/skybyte-acme.timer ]] || systemctl disable --now skybyte-acme.timer;;
  6) [[ ! -e $BASE/acme-state.json ]] || { err "$(L '已有成功申请，拒绝清理' 'Successful issuance exists; refusing cleanup')";return 1; }
   confirm "$(L '删除本工具未完成的 ACME 申请目录后重试？' 'Delete the incomplete managed ACME attempt for retry?')" && rm -rf "$BASE/acme";;
  0) return 0;;*) return 1;;
 esac
}

acme_remove(){
 acme_guard || return 1
 [[ ! -f $SYSTEMD_DIR/skybyte-acme.timer ]] || systemctl disable --now skybyte-acme.timer || return 1
 [[ ! -f $SYSTEMD_DIR/skybyte-acme.service ]] || systemctl stop skybyte-acme.service || return 1
 rm -f "$SYSTEMD_DIR/skybyte-acme.timer" "$SYSTEMD_DIR/skybyte-acme.service" "$BASE/acme-state.json"
 [[ ! -d $BASE/acme ]] || rm -rf "$BASE/acme"
}
