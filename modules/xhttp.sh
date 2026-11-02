# Integrated XHTTP uses an isolated shell and Python namespace, never a second manager download.
xhttp_backend(){
 SKYBYTE_SB_BASE="$BASE" SKYBYTE_SB_CONF="$CONF" python3 - --root "$BASE/xhttp" --binary "$BASE/xhttp-core/xray" --unit "$SYSTEMD_DIR/skybyte-sb-xhttp.service" "$@" <<'PY_XHTTP'
# @include xhttp_core_main.py
PY_XHTTP
}
xhttp_latest(){
 curl -q -fsSL --proto '=https' --proto-redir '=https' --connect-timeout 10 --max-time 25 https://api.github.com/repos/XTLS/Xray-core/releases/latest | python3 -c '
import json,re,sys
r=json.load(sys.stdin);tag=r.get("tag_name","")
if r.get("draft") is not False or r.get("prerelease") is not False or not isinstance(tag,str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+",tag):raise SystemExit("Invalid official stable Xray release / 官方稳定版信息无效")
print(tag)'
}
# shellcheck disable=SC2329 # Nested callbacks execute only inside this isolated frontend.
xhttp_command() (
 local SKYBYTE_XRAY_DIR=$BASE/xhttp SKYBYTE_XRAY_LIB=$BASE/xhttp-core
 local SKYBYTE_XRAY_BINARY=$BASE/xhttp-core/xray SKYBYTE_XRAY_UNIT=$SYSTEMD_DIR/skybyte-sb-xhttp.service
 local CORE_VERSION='' LANGUAGE=zh
 [[ ${LANGUAGE_CHOICE:-zh_CN} != en_US ]] || LANGUAGE=en
 export SKYBYTE_XRAY_DIR SKYBYTE_XRAY_BINARY SKYBYTE_XRAY_UNIT
 # Definitions only; these names remain isolated from the sing-box manager.
# @include modules/xhttp_common.sh
# @include modules/xhttp_service.sh
# @include modules/xhttp_configuration.sh
# @include modules/xhttp_subscription.sh
# @include modules/xhttp_backup.sh
# @include modules/xhttp_reality.sh
# @include modules/xhttp_install.sh
# @include modules/xhttp_automatic.sh
 helper(){ xhttp_backend "$@"; }
 # Share the parent's APT lock handling and repository compatibility.
 apt_refresh(){ apt_install --download-only --no-install-recommends ca-certificates; }
 install_environment_check(){
  local args=(--project xray --language "$LANGUAGE" --phase environment --os-release "$OS_RELEASE")
  [[ ${1:-} == xhttp-tls ]] || args+=(--reality)
  report_output install_check_engine "${args[@]}" --paths "$SKYBYTE_XRAY_DIR" "$SKYBYTE_XRAY_LIB" "${TMPDIR:-/tmp}"
 }
 install_port_check(){ report_output install_check_engine --project xray --language "$LANGUAGE" --phase ports --listen "$2" --tcp-port "$1"; }
 install_download_check(){ report_output install_check_engine --project xray --language "$LANGUAGE" --phase download; }
 install_reality_target(){
  helper reality-input --target "$2" --sni "$1" || return 1
  report_output reality_engine --project xray --language "$LANGUAGE" --target "$2" --sni "$1"
 }
 ensure_binary(){
  local dependency missing=false
  for dependency in curl openssl ss flock;do command -v "$dependency" >/dev/null || missing=true;done
  [[ $missing != true ]] || apt_install --no-install-recommends curl ca-certificates openssl iproute2 util-linux || return 1
  helper guard && lib_guard || return 1
  if [[ ! -x $SKYBYTE_XRAY_BINARY ]];then
   local candidate asset
   CORE_VERSION=$(xhttp_latest) || { error '无法查询 Xray 最新稳定版，停止下载。' 'Cannot resolve latest stable Xray; download stopped.';return 1; }
   asset=$(core_asset) || return 1
   candidate=$(mktemp "$SKYBYTE_XRAY_LIB/.download.XXXXXX") || return 1
   say "正在下载并校验 Xray $CORE_VERSION" "Downloading and verifying Xray $CORE_VERSION"
   if ! helper download --file "$candidate" --asset "$asset" --tag "$CORE_VERSION" || ! "$candidate" version >/dev/null;then rm -f -- "$candidate";return 1;fi
   mv -f -- "$candidate" "$SKYBYTE_XRAY_BINARY" || return 1
  fi
 }
 choose_kind(){
  local selected
  menu '1. XHTTP + Reality\n2. XHTTP + TLS / CDN\n0. 返回' '1. XHTTP + Reality\n2. XHTTP + TLS / CDN\n0. Back' >&2
  selected=$(ask '> ' '> ') || return 1
  case $selected in 1)printf xhttp-reality;;2)printf xhttp-tls;;*)return 1;;esac
 }
 # All configuration changes open active UFW ports before committing the stage.
 apply_stage(){
  local ports stage=$1 firewall_state
  ports=$(helper stage-ports --stage "$stage") || return 1
  firewall_state=$(helper ufw-state) || { helper finalize --stage "$stage";return 1; }
  if [[ $firewall_state == active && -n $ports ]];then
   while IFS= read -r number;do
    if ! helper firewall-allow --ports "$number";then helper finalize --stage "$stage";return 1;fi
   done <<< "$ports"
   warn '新增 UFW 放行规则在后续失败时也会保留，请核对；云安全组需另外放行。' 'New UFW allow rules remain on later failure; inspect them and allow provider access separately.'
  fi
  xhttp_original_apply_stage "$@"
 }
 case ${1:-} in
  guided) need_root;recover || return 1;xhttp_install_automatic;;
  install) need_root;recover || return 1;install_node "$2";;
  show) [[ ! -f $SKYBYTE_XRAY_DIR/state.json ]] || show_nodes;;
  parameters) helper parameters --language "$LANGUAGE";;
  qr) [[ -f $SKYBYTE_XRAY_DIR/nodes.txt ]] || return 1
      if ! command -v qrencode >/dev/null;then confirm '安装二维码工具？' 'Install QR tooling?' || return 0;apt_install --no-install-recommends qrencode || return 1;fi
      qr_nodes;;
  service) helper guard || return 1;recover || return 1;service_menu "$2";;
  edit) helper guard || return 1;recover || return 1;edit_nodes "$2";;
  update) CORE_VERSION=$(xhttp_latest) || return 1;recover || return 1;update_core;;
  backup) [[ $# != 2 ]] || { helper backup --file "$2";return; };make_backup;;
  restore) restore_backup;;
  guard) [[ ! -e $SKYBYTE_XRAY_DIR && ! -L $SKYBYTE_XRAY_DIR ]] || helper guard;;
  ports) [[ ! -e $SKYBYTE_XRAY_DIR && ! -L $SKYBYTE_XRAY_DIR ]] || helper port-numbers;;
  purge) helper guard && lib_guard && recover || return 1
    if [[ ${2:-} != --confirmed ]];then confirm '备份后卸载 XHTTP 节点与独立 Xray 核心？保留 sing-box。' 'Back up and remove XHTTP/Xray, keeping sing-box?' || return 0;fi
    make_backup || return 1
    helper purge-plan >/dev/null || return 1
    if [[ -f $SKYBYTE_XRAY_UNIT ]];then systemctl disable --now skybyte-sb-xhttp.service || return 1;fi
    helper purge || return 1
    systemctl daemon-reload || return 1;;
  *) return 1;;
 esac
)
xhttp_menu(){
 if [[ ${1:-} == --menu ]];then
  prompt_options 'XHTTP（按需安装 Xray；独立配置与服务）
1. 自动部署 XHTTP + Reality
2. 自动部署 XHTTP + TLS / CDN
3. 查看 XHTTP 节点与导出
4. 查看节点参数（注意保密）
5. 小火箭二维码（客户端需支持 XHTTP）
6. 服务、日志与配置检查
7. 编辑节点 / 修改端口 / 删除协议
8. 更新 Xray 内核（最新稳定版）
9. 备份 XHTTP
10. 恢复 XHTTP 备份
11. 卸载 XHTTP / Xray（保留 sing-box）
12. 自定义安装（手动端口 / 地址 / 路径 / 模式）
0. 返回' 'XHTTP (on-demand Xray; separate config and service)
1. Guided XHTTP + Reality
2. Guided XHTTP + TLS / CDN
3. Show XHTTP nodes and exports
4. Show private node parameters
5. Shadowrocket QR (XHTTP client required)
6. Service, logs and config checks
7. Edit nodes / ports / remove protocols
8. Update Xray (latest stable)
9. Back up XHTTP
10. Restore XHTTP backup
11. Remove XHTTP / Xray (keep sing-box)
12. Custom install (manual ports / address / path / mode)
0. Back';return
 fi
 case ${1:-0} in
  1)xhttp_guided_install xhttp-reality;;2)xhttp_guided_install xhttp-tls;;3)report_output xhttp_command show;;4)report_output xhttp_command parameters;;5)xhttp_command qr;;
  8)xhttp_command update;;9)xhttp_command backup;;10)xhttp_command restore;;11)xhttp_command purge;;0)return 0;;*)return 1;;
 esac
}
xhttp_service_menu(){
 if [[ ${1:-} == --menu ]];then prompt_options '1. 状态
2. 启动
3. 停止
4. 重启
5. 配置检查
6. 日志
0. 返回' '1. Status
2. Start
3. Stop
4. Restart
5. Check config
6. Logs
0. Back';return;fi
 xhttp_command service "$1"
}
xhttp_edit_menu(){
 if [[ ${1:-} == --menu ]];then prompt_options '1. 重命名
2. 删除协议
3. 更新 TLS 证书
4. 修改地址 / 端口 / 路径
5. 修改节点端口
0. 返回' '1. Rename
2. Remove protocol
3. Refresh TLS certificate
4. Edit address / port / path
5. Change node port
0. Back';return;fi
 xhttp_command edit "$1"
}
view_all_nodes(){
 if [[ -f $META ]];then exports || return 1;fi
 if [[ -f $BASE/xhttp/state.json ]];then xhttp_command show || return 1;fi
 if [[ ! -f $META && ! -f $BASE/xhttp/state.json ]];then say '尚未安装节点。' 'No nodes installed.';fi
}
view_all_parameters(){
 if [[ -f $META ]];then node_parameters || return 1;fi
 if [[ -f $BASE/xhttp/state.json ]];then xhttp_command parameters || return 1;fi
 if [[ ! -f $META && ! -f $BASE/xhttp/state.json ]];then node_parameters;fi
}

xhttp_custom_menu(){
 if [[ ${1:-} == --menu ]];then prompt_options '1. XHTTP + Reality
2. XHTTP + TLS / CDN
0. 返回' '1. XHTTP + Reality
2. XHTTP + TLS / CDN
0. Back';return;fi
 case $1 in 1)xhttp_command install 2;;2)xhttp_command install 3;;*)return 1;;esac
}
