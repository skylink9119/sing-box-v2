# lib/common.sh — build-time module; assembled by scripts/build.py.
# Language preference is independent of sing-box configuration.
LANG_FILE="$BASE/language.conf"
LANGUAGE_CHOICE=""
load_language() {
  if [[ -f "$LANG_FILE" ]]; then
    local value
    value=$(cat "$LANG_FILE")
    case "$value" in zh_CN|en_US) LANGUAGE_CHOICE=$value;; esac
  fi
}
select_language() {
  local choice
  while :; do
    printf '%s\n========== Language / 语言 ==========\n 1. 简体中文\n 2. English\n=======================================\n%s' "$GREEN" "$RESET"
    prompt_read '请选择语言 / Select language [1/2]: ' choice || return 1
    case "$choice" in 1) LANGUAGE_CHOICE=zh_CN;; 2) LANGUAGE_CHOICE=en_US;; *) continue;; esac
    printf '%s\n' "$LANGUAGE_CHOICE" > "$LANG_FILE"
    chmod 600 "$LANG_FILE"
    break
  done
}
# Keep input prompts green, resetting before the user types. Hidden token input stays hidden.
prompt_read(){
 if [[ ${3:-} == secret ]]; then read -rs -p "${GREEN}$1${RESET}" "$2"
 else read -r -p "${GREEN}$1${RESET}" "$2"; fi
}
prompt_options(){ printf '%s%s%s\n' "$GREEN" "$(L "$1" "$2")" "$RESET"; }
say(){ printf '%s\n' "$(L "$1" "$2")"; }
L() { if [[ "$LANGUAGE_CHOICE" == en_US ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
 GREEN=$'\033[1;32m'; RED=$'\033[1;31m'; YELLOW=$'\033[1;33m'; CYAN=$'\033[1;36m'; RESET=$'\033[0m'
else GREEN=''; RED=''; YELLOW=''; CYAN=''; RESET=''; fi
YOUTUBE='https://www.youtube.com/@SKYBYTE9119'
ok(){ printf '%s✔ %s%s\n' "$GREEN" "$*" "$RESET"; }
warn(){ printf '%s⚠ %s%s\n' "$YELLOW" "$*" "$RESET"; }
err(){ printf '%s✖ %s%s\n' "$RED" "$*" "$RESET" >&2; }
# @include lib/packages.sh
# @include lib/shortcut.sh
need_root(){ [[ $EUID == 0 ]] || { err "$(L '需要 root 权限' 'Root privileges required')"; exit 1; }; }
confirm(){ local answer; prompt_read "$1 [y/N]: " answer || return 1; [[ $answer =~ ^[[:space:]]*[Yy][[:space:]]*$ ]]; }
# Keep report commands attached to the terminal (vnStat live mode needs a TTY).
report_output(){
 local report_status=0 report_reset=$RESET
 if [[ ! -t 1 || -n ${NO_COLOR:-} ]];then "$@";return $?;fi
 printf '%s' "$YELLOW"
 local GREEN=$YELLOW RED=$YELLOW CYAN=$YELLOW RESET=$YELLOW
 (
  export NO_COLOR=1 SYSTEMD_COLORS=0 CLICOLOR=0
  "$@"
 ) || report_status=$?
 printf '%s' "$report_reset"
 return "$report_status"
}
notice(){ if [[ "$LANGUAGE_CHOICE" == en_US ]]; then cat <<'EOF_EN'
[LEGAL & PRIVACY NOTICE] Use only for lawful networking education and server administration. You must comply with applicable law and service terms. Updating software or changing firewall/network settings may interrupt service or cause data loss; make backups first. Provided as-is to the extent permitted by law. Third-party components retain their licenses.
Installation and updates can contact sky9119.cc (Cloudflare HTTPS redirects), github.com, api.github.com and GitHub release CDNs; these services can see your source IP. Installation queries api.ipify.org/api64.ipify.org for your public address. Optional ACME contacts Let's Encrypt and, for DNS validation, Cloudflare; public certificates disclose domain names. HTTPS subscriptions serve personal credential exports only to token holders. Optional streaming probes contact the selected platforms; WARP installation/tests contact Cloudflare. Those services can see the egress IP and request metadata. Reports stay local in /etc/singbox-v2/reports; manage retention yourself. WARP sends selected traffic through Cloudflare. No developer telemetry or intentional upload of node credentials. Weekly automatic updates have been removed. HY2 requires TLS. A no-domain self-signed certificate mode is available, but clients must securely trust the certificate.
Optional Argo connects to Cloudflare, which terminates outer TLS and can inspect WebSocket payloads. Tunnel tokens are stored locally and included in private backups.
EOF_EN
else cat <<'EOF'
【法律与隐私披露】此工具仅供合法网络技术学习和服务器管理；使用者应遵守适用法律和服务条款。更改防火墙、网络参数及更新软件可能导致中断或损失，请提前备份。软件按现状提供，不排除依法不得排除的责任。第三方软件遵循其许可证。
安装/更新可能连接：sky9119.cc（Cloudflare HTTPS 跳转）、github.com、api.github.com、GitHub 发布文件 CDN，访问服务会暴露请求来源 IP。可选 ACME 会访问 Let's Encrypt，DNS 验证还访问 Cloudflare；公开证书会披露域名。HTTPS订阅仅向持有Token者返回个人客户端凭据。安装时 api.ipify.org/api64.ipify.org 用于识别公网地址；可选流媒体检测访问对应平台，WARP 安装/检测访问 Cloudflare。第三方可能记录出口 IP、查询目标和请求时间。报告保存在本地 /etc/singbox-v2/reports，请自行清理。WARP 将选定流量交由 Cloudflare 转发。无开发者遥测或上传节点密钥；请勿公开包含凭据的配置和导出文件。每周自动更新已移除。HY2 必须有 TLS 证书，无域名用户可生成自签名证书，客户端必须正确配置信任，不能默认跳过证书验证。
可选 Argo 连接 Cloudflare，外层 TLS 在其边缘终止，可检查 WebSocket 载荷。隧道 Token 保存在本地并包含在私密备份中。
EOF
fi
}
require_cmd(){ command -v "$1" >/dev/null || { err "$(L "缺少命令 $1" "Missing command: $1")"; return 1; }; }
valid_port(){ [[ $1 =~ ^[0-9]{1,5}$ ]] && (( 1 <= 10#$1 && 10#$1 <= 65535 )); }
state(){ python3 - "$META" "$1" <<'PY'
import json,sys
with open(sys.argv[1]) as f: d=json.load(f)
print(d.get(sys.argv[2],''))
PY
}
protocol_mode(){
 python3 - "$CONF" <<'PY'
import json,sys
p={i['type'] for i in json.load(open(sys.argv[1]))['inbounds']}
if {'vless','hysteria2'} <= p: print('3')
elif 'vless' in p: print('1')
elif 'hysteria2' in p: print('2')
else: raise ValueError('No supported installed protocols')
PY
}
check_owned(){
 [[ -f $META && -f $CONF ]] || { err "$(L '未发现由本脚本部署的节点' 'No deployment managed by this script was found')"; return 1; }
 local owned_path
 for owned_path in "$BASE" "$META" "$CONF" "$BIN" "$BACKUP" "$(dirname "$CONF")";do
  [[ ! -L $owned_path ]] || { err "$(L '托管路径是符号链接，拒绝修改' 'Managed path is a symlink; refusing changes')";return 1; }
 done
}
