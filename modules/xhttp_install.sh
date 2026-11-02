# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
# modules/install.sh — build-time module; assembled by scripts/build.py.
install_node(){
 local choice kind node_name node_port host sni target listen path='' mode=auto cert='' private_key='' stage
 local ipv6_install='' ipv6_status ipv6_ufw_status
 local flags=() apply_options=()
 choice=${1:-2}
 case $choice in 2|3);;*)return 1;;esac
 case $choice in 1) kind=vision; node_port=443;; 2) kind=xhttp-reality; node_port=443;; 3) kind=xhttp-tls; node_port=2053;; 4) run_submenu installation_check_menu;return;; 5) run_submenu ipv6_install_menu;return;; 0) return 0;; *) return 1;; esac
 if [[ $ipv6_install == ipv6 ]];then
  if ! command -v ip >/dev/null;then install_environment_check "$kind" || return 1;fi
  host=$(ipv6_install_address) || { ipv6_status=$?;[[ $ipv6_status == 2 ]] && return 0;return 1; }
  listen=::
  warn '使用所选 IPv6 作为节点连接地址，监听支持双栈。客户端网络必须支持 IPv6，云安全组和系统防火墙需放行 IPv6 TCP 端口。纯 IPv6 VPS 访问 IPv4 网站需要另行配置可用出站。已有同协议节点请用 l → 9 增加 IPv6 备用入口。' 'The selected IPv6 is the client address with a dual-stack listener. Client IPv6 and provider/host IPv6 TCP rules are required. IPv6-only VPSs need a separate working egress for IPv4-only sites. Use l → 9 for IPv6 backups on an existing protocol.'
 fi
 node_name=$(ask '节点名称 [SKYBYTE]：' 'Node name [SKYBYTE]: ') || return 1; node_name=${node_name:-SKYBYTE}-$kind
 [[ $ipv6_install != ipv6 ]] || node_name+=-IPv6
 node_port=$(ask "监听 TCP 端口 [$node_port]：" "TCP listen port [$node_port]: ") || return 1
 case $kind in vision|xhttp-reality) node_port=${node_port:-443};; *) node_port=${node_port:-2053};; esac
 if [[ $ipv6_install != ipv6 ]];then
  listen=$(ask '监听：1 IPv4  2 双栈 IPv4+IPv6 [1]：' 'Listen: 1 IPv4  2 Dual-stack IPv4+IPv6 [1]: ') || return 1
  case ${listen:-1} in 1) listen=0.0.0.0;; 2) listen=::;; *) return 1;; esac
  while :; do
   host=$(ask '客户端连接地址（必填：本 VPS 的公网 IP 或域名）：' 'Client connection address (required: this VPS public IP/domain): ') || return 1
   [[ $host =~ [^[:space:]] ]] && break
   warn '此项没有默认值，请填写本 VPS 的公网 IP 或域名。' 'There is no default; enter this VPS public IP or domain.'
  done
 fi
 helper preflight --port "$node_port" --listen "$listen" --address "$host" --name "$node_name" --kind "$kind" || return 1
 install_environment_check "$kind" && install_port_check "$node_port" "$listen" || return 1
 if [[ $kind == xhttp-tls ]]; then
  sni=$(ask '证书域名 / TLS SNI：' 'Certificate domain / TLS SNI: ') || return 1
  cert=$(ask '已有可信 fullchain 证书文件绝对路径：' 'Absolute path to trusted fullchain certificate: ') || return 1
  private_key=$(ask '私钥文件绝对路径（不修改源文件）：' 'Absolute private-key path (source is preserved): ') || return 1
  helper tls-input --sni "$sni" --cert "$cert" --key "$private_key" || return 1
  local cdn
  if [[ $ipv6_install != ipv6 ]];then
   cdn=$(ask '通过 CDN 连接？[y/N]：' 'Use a CDN? [y/N]: ') || return 1
   if confirmed "$cdn"; then flags+=(--cdn); mode=packet-up; fi
   warn 'CDN 的 DNS、HTTPS 端口及回源 TLS 验证须在提供商后台配置。' 'Configure CDN DNS, supported HTTPS port and verified origin TLS at your provider.'
  fi
 else
  sni=$(choose_reality_sni) || return 1
  [[ -n $sni ]] || return 0
  target=$(ask "握手目标 [$sni:443]：" "Handshake target [$sni:443]: ") || return 1; target=${target:-$sni:443}
  install_reality_target "$sni" "$target" || return 1
 fi
 if [[ $kind == xhttp-* ]]; then
  path=$(ask 'XHTTP 路径（回车自动生成）：' 'XHTTP path (Enter to generate): ') || return 1
  local selected
  selected=$(ask "模式 [$mode]（auto / packet-up / stream-up / stream-one）：" "Mode [$mode] (auto / packet-up / stream-up / stream-one): ") || return 1
  mode=${selected:-$mode}
 fi
 warn '请放行实际 TCP 端口，可用菜单 d 管理系统防火墙；配置检查不等于公网或 CDN 已连通。' 'Allow the actual TCP port using menu d for the host firewall; validation does not prove public/CDN connectivity.'
 if ! confirm '安装并启动所选节点？' 'Install and start the selected node?'; then
  say '已取消节点安装，未下载核心或更改节点配置。' 'Node installation cancelled; no core download or node configuration changes.'
  return 0
 fi
 install_download_check || return 1
 ensure_binary || { error '核心准备失败，具体原因见上方提示。' 'Core preparation failed; see the reason above.'; return 1; }
 flags+=(--kind "$kind" --port "$node_port" --listen "$listen" --address "$host" --sni "$sni" --name "$node_name")
 if [[ $kind == xhttp-tls ]]; then flags+=(--cert "$cert" --key "$private_key")
 else flags+=(--target "$target"); fi
 [[ $kind != xhttp-* ]] || flags+=(--path "$path" --mode "$mode")
 stage=$(helper prepare "${flags[@]}") || { error '节点配置准备失败，具体原因见上方提示。' 'Node configuration preparation failed; see the reason above.'; return 1; }
 apply_options=("$stage" yes)
 if [[ $ipv6_install == ipv6 ]];then
  if ! ipv6_engine check-install "$host";then helper finalize --stage "$stage";return 1;fi
  if ! ipv6_ufw_status=$(helper ufw-state);then helper finalize --stage "$stage";return 1;fi
  if [[ $ipv6_ufw_status == active ]];then
   warn '先放行新端口；后续安装失败时，新增放行规则会保留，请自行核对。' 'Allowing the new port first; added rules remain if installation later fails. Review them if needed.'
   if ! helper firewall-allow --ports "$node_port";then helper finalize --stage "$stage";return 1;fi
  fi
  apply_options+=("ipv6-install:$node_port")
 fi
 apply_stage "${apply_options[@]}" || { error '安装失败，原配置已保留或回退。' 'Install failed; previous configuration retained or restored.'; return 1; }
 show_nodes
}
