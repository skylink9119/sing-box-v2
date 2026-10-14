rescue_engine(){
 python3 - "$@" <<'PY_RESCUE'
# @include rescue.py
PY_RESCUE
}
rescue_dependencies(){
 local name missing=false
 for name in curl python3 sha256sum tar ss flock;do command -v "$name" >/dev/null || missing=true;done
 if [[ $missing == true ]];then
  [[ -z ${SKYBYTE_ASSET_DIR:-} ]] || { err "$(L '离线模式缺少依赖；请先从发行版软件源安装 curl、python3、coreutils、tar、iproute2 和 util-linux。' 'Offline dependencies missing: install curl, python3, coreutils, tar, iproute2 and util-linux from distro packages first.')";return 1; }
  apt_install --no-install-recommends curl ca-certificates python3 coreutils tar iproute2 util-linux || return 1
 fi
 if ! require_cmd systemctl || ! systemctl show --property=Version --value >/dev/null;then err "$(L '需要运行中的 systemd；不支持无 systemd 的容器。' 'A running systemd is required; containers without systemd are unsupported.')";return 1;fi
}
rescue_bootstrap_core() (
 local stage='' committed=false final_bin=$BIN final_conf=$CONF final_meta=$META final_base=$BASE name bind_family listen base_existed=false
 trap installation_cleanup EXIT
 need_root
 # shellcheck source=/dev/null
 . "$OS_RELEASE"
 case ${ID:-} in ubuntu|debian);;*) err 'Ubuntu/Debian required';return 1;;esac
 for name in "$CONF" "$META" "$BIN" "$SYSTEMD_DIR/sing-box.service";do [[ ! -e $name && ! -L $name ]] || { err "$(L '已有配置或内核，拒绝覆盖' 'Existing configuration/core; refusing overwrite')";return 1; };done
 command -v sing-box >/dev/null && { err 'Existing sing-box found';return 1; }
 [[ ! -L $BASE && ( ! -e $BASE || -d $BASE ) ]] || { err "$(L '管理数据目录异常，拒绝写入' 'Manager data path is unsafe; refusing writes')";return 1; }
 argo_guard || return 1
 for name in argo-state.json argo-server.json argo.token argo-empty.yml cloudflared;do [[ ! -e $BASE/$name ]] || return 1;done
 if systemctl list-unit-files sing-box.service --no-legend 2>/dev/null | grep -q sing-box;then return 1;fi
 warn "$(L '将安装仅含回环 WS 节点的 Argo 依赖，不占用公网 443、不查询公网 IP。需要能下载官方软件并主动连接 Cloudflare。' 'Bootstraps a loopback-only Argo origin, without public port 443 or public-IP lookup. Official downloads and outbound Cloudflare connectivity are required.')"
 confirm "$(L '准备 Argo 应急部署？' 'Prepare standalone Argo deployment?')" || return 2
 rescue_dependencies || return 1
 [[ ! -d $BASE ]] || base_existed=true
 mkdir -p "$BASE" "$(dirname "$BIN")" "$(dirname "$CONF")" || return 1
 [[ $base_existed == true ]] || chmod 700 "$BASE" || return 1
 bind_family=$(rescue_engine family) || return 1
 case $bind_family in 4)listen=0.0.0.0;;6)listen=::;;*)listen=::;;esac
 stage=$(mktemp -d "$BASE/install.XXXXXX") || return 1
 mkdir -m 700 "$stage/config"
 download_binary "$CORE_RECOMMENDED" "$stage/sing-box" || return 1
 python3 - "$stage" "$listen" <<'PY_RESCUE_CORE'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1])
(p/'config/config.json').write_text(json.dumps({'log':{'level':'warn'},'inbounds':[],'outbounds':[{'type':'direct','tag':'direct'}],'route':{'final':'direct'}}))
(p/'state.json').write_text(json.dumps({'deployment':'argo-only','node_name':'SKYBYTE','mode':'0','cert_mode':'0','cert_path':'','managed_certificates':[],'ip':'127.0.0.1','listen':sys.argv[2],'hop':False}))
PY_RESCUE_CORE
 "$stage/sing-box" check -c "$stage/config/config.json" || return 1
 installation_commit "$stage" "$BIN" "$CONF" "$META" "$BASE" || return 1
 setup_service || return 1
 systemctl disable --now sing-box.service || return 1
 committed=true
)
admin_restart(){
 if python3 - "$CONF" <<'PY_ADMIN_LISTENER'
import json,sys
sys.exit(0 if json.load(open(sys.argv[1])).get('inbounds') else 1)
PY_ADMIN_LISTENER
 then systemctl restart sing-box && service_healthy
 else systemctl disable --now sing-box.service;fi
}
argo_network_settings(){
 argo_guard || return 1
 [[ -f $BASE/argo-state.json ]] || return 1
 local edge transport snap active=false
 prompt_options 'Cloudflare 连接地址族：1 自动  2 IPv4  3 IPv6' 'Cloudflare address family: 1 Auto  2 IPv4  3 IPv6'
 prompt_read '> ' edge || return 0
 case ${edge:-1} in 1) edge=auto;;2) edge=4;;3) edge=6;;*) return 1;;esac
 prompt_options '隧道传输：1 自动  2 QUIC/UDP 7844  3 HTTP2/TCP 7844' 'Tunnel transport: 1 Auto  2 QUIC/UDP 7844  3 HTTP2/TCP 7844'
 prompt_read '> ' transport || return 0
 case ${transport:-1} in 1) transport=auto;;2) transport=quic;;3) transport=http2;;*) return 1;;esac
 warn "$(L '重启临时隧道会更换域名，需要重新导入节点。HTTP2 仍需出站 TCP 7844，不能通过 TCP 443 代替。' 'Restarting a Quick Tunnel changes its hostname; re-import the node. HTTP2 still requires outbound TCP 7844, not TCP 443.')"
 confirm "$(L '应用隧道网络设置？' 'Apply tunnel network settings?')" || return 0
 snap=$(backup) || return 1
 systemctl is-active --quiet skybyte-argo-tunnel.service && active=true
 [[ $active != true ]] || argo_stop || return 1
 rescue_engine options "$BASE/argo-state.json" "$edge" "$transport" || return 1
 if [[ $active == true ]] && ! argo_start;then
  argo_stop || :;cp "$snap/argo-state.json" "$BASE/argo-state.json";argo_clear_ready;argo_start || :
  err "$(L '新设置未连接，已恢复原设置；临时域名仍可能变化。' 'New settings failed; previous settings restored. Quick hostname may still change.')";return 1
 fi
 ok "$(L '隧道网络设置已保存' 'Tunnel network settings saved')"
}
rescue_help(){
 say '受限网络部署：独立 Argo 不要求公网入站端口；NAT 的直连节点需要服务商实际映射。' 'Restricted networks: standalone Argo needs no public inbound ports; direct NAT nodes need actual provider mappings.'
 say 'Argo 临时隧道只用于应急代理连通，不是 SSH/主机救援通道；Quick Tunnel 仅适合测试，地址、并发和可用性均无保证。' 'Argo Quick Tunnel can temporarily restore proxy connectivity; it is not SSH/host recovery. Quick Tunnels are for testing, with no hostname, concurrency or uptime guarantee.'
 say '纯 IPv6：Argo 自动选择 IPv6；访问仅 IPv4 网站需可用的双栈 WARP 网关。导入配置的 Peer Endpoint 必须能经原生网络到达。' 'IPv6-only: Argo selects IPv6; IPv4-only sites need a working dual-stack WARP gateway. The imported Peer Endpoint must be reachable over native networking.'
 say 'GitHub 无法下载时：从可信机器取回对应架构的 sing-box 与 cloudflared 官方文件及 Release API 元数据，复制到同一离线目录；软件包依赖仍需已安装或能访问 Debian/Ubuntu 软件源。' 'If GitHub downloads fail: copy architecture-matched official sing-box/cloudflared files and their Release API metadata into one offline directory. System dependencies must already exist or be available from Debian/Ubuntu repositories.'
 say '支持 Ubuntu/Debian + systemd，内核下载支持 amd64/arm64/armv7/386；小内存机器只启用需要的服务，不能保证任意架构或内存容量。' 'Requires Ubuntu/Debian + systemd. Downloads support amd64/arm64/armv7/386; enable only needed services on small systems. Arbitrary architectures/capacity are not guaranteed.'
 say 'Argo 使用 VLESS+WS+TLS，不能透传 HY2/QUIC。Cloudflare 出站需要 TCP 或 UDP 7844；HTTP2 仍使用 TCP 7844，不会回退到 443。' 'Argo uses VLESS+WS+TLS and cannot carry HY2/QUIC. Cloudflare egress requires TCP or UDP 7844; HTTP2 still uses TCP 7844 and does not fall back to 443.'
}
rescue_menu(){
 local choice mode host vp hp directory edge
 prompt_options $' 1. Argo 临时隧道应急部署\n 2. Argo 固定隧道部署\n 3. 自定义监听端口安装（IPv6 / NAT）\n 4. NAT 公网地址与映射端口\n 5. Argo 地址族与传输设置\n 6. WARP 双栈补全\n 7. 检查 Cloudflare 出站 TCP 7844\n 8. 使用离线官方安装包\n 9. 使用说明\n 0. 返回' $' 1. Standalone Argo Quick Tunnel\n 2. Standalone Argo Named Tunnel\n 3. Install with custom ports (IPv6/NAT)\n 4. NAT public address and mapped ports\n 5. Argo address family/transport\n 6. WARP dual-stack egress\n 7. Check Cloudflare outbound TCP 7844\n 8. Use offline official assets\n 9. Usage guide\n 0. Back'
 prompt_read '> ' choice || return 0
 case $choice in
  1) argo_install quick;;2) argo_install named;;
  3) prompt_options '1 Reality  2 HY2  3 双协议' '1 Reality  2 HY2  3 Dual';prompt_read '> ' mode || return 0;install_protocol "$mode" custom;;
  4) check_owned || return 1
   prompt_read "$(L 'NAT 公网 IP / 域名：' 'NAT public IP/hostname: ')" host || return 0
   host=$(rescue_engine address "$host") || return 1
   prompt_read "$(L '公网 Reality TCP 端口 [0=本机端口]：' 'Public Reality TCP port [0=local port]: ')" vp || return 0
   prompt_read "$(L '公网 HY2 UDP 端口 [0=本机端口]：' 'Public HY2 UDP port [0=local port]: ')" hp || return 0
   warn "$(L '只更新管理员节点导出；不会替服务商创建 NAT。受限用户端口需单独映射，HY2 证书身份保持原值，跳跃将关闭。' 'Updates admin exports only; does not create provider NAT. User ports need separate mappings; HY2 certificate identity is retained and hopping is disabled.')"
   confirm "$(L '保存 NAT 导出设置？' 'Save NAT export settings?')" && configuration_apply nat_exports "$host" "${vp:-0}" "${hp:-0}";;
  5) argo_network_settings;;
  6) check_owned || return 1;edge=$(rescue_engine family) || return 1
   say '使用你已有的合法 WARP WireGuard 双栈配置；原生 IPv6 必须使用 IPv6 Peer Endpoint。默认 MTU 1280，无需 /dev/net/tun。' 'Use your own valid dual-stack WARP WireGuard profile. Native IPv6 needs an IPv6 Peer Endpoint. Default MTU 1280; no /dev/net/tun is required.'
   warn "$(L '补全仅作用于托管节点；全局 WARP 会改变这些节点的出口，不修改系统默认路由。' 'Completion applies only to managed nodes. Global WARP changes their egress, without changing the system default route.')"
   prompt_options '1 全部节点流量走 WARP  2 仅流媒体与 AI 域名' '1 All node traffic via WARP  2 Media/AI domains only';prompt_read '> ' mode || return 0
   case $mode in 1) mode=global;;2) mode=restricted;;*) return 1;;esac
   warp_import_gateway "$edge" "$mode" && warp_dualstack;;
  7) edge=$(rescue_engine family);say "原生路由选择：$edge" "Native route selection: $edge"
   edge=$(rescue_engine edge "$edge") || return 1
   say "Cloudflare 入口 TCP 7844 可连接数量：$edge/2；UDP 和隧道注册尚未验证。" "Reachable Cloudflare TCP 7844 endpoints: $edge/2; UDP and tunnel registration remain unverified.";;
  8) say '文件名：sing-box-1.14.3-linux-<架构>.tar.gz、sing-box-1.14.3-release.json、cloudflared-linux-<架构>、cloudflared-release.json。' 'Files: sing-box-1.14.3-linux-<arch>.tar.gz, sing-box-1.14.3-release.json, cloudflared-linux-<arch>, cloudflared-release.json.'
   prompt_read "$(L '可信离线安装包目录（绝对路径；回车取消）：' 'Trusted offline asset directory (absolute; Enter cancels): ')" directory || return 0
   [[ -n $directory ]] || return 0
   [[ $directory == /* && -d $directory && ! -L $directory ]] || return 1
   if [[ -n ${SKYBYTE_SESSION_FILE:-} ]];then
    [[ -f $SKYBYTE_SESSION_FILE && ! -L $SKYBYTE_SESSION_FILE ]] || return 1
    printf '%s\n' "$directory" > "$SKYBYTE_SESSION_FILE" || return 1
   fi
   export SKYBYTE_ASSET_DIR=$directory
   say '已为当前脚本会话启用离线目录；下次运行需要重新选择。元数据与软件包都必须来自可信来源，校验不证明元数据本身未被篡改。' 'Offline directory enabled for this session; select it again next run. Both metadata and assets must be trusted; a checksum does not authenticate altered metadata.';;
  9) rescue_help;;0) return 0;;*) return 1;;
 esac
}
