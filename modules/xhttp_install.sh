# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
# modules/install.sh — build-time module; assembled by scripts/build.py.
install_node(){
 local choice kind node_name node_port host sni target listen path='' mode=auto cert='' private_key='' stage
 local flags=()
 choice=${1:-2}
 case $choice in 2|3);;*)return 1;;esac
 case $choice in 2) kind=xhttp-reality; node_port=443;; 3) kind=xhttp-tls; node_port=2053;; *) return 1;; esac
 node_name=$(ask '节点名称 [SKYBYTE]：' 'Node name [SKYBYTE]: ') || return 1; node_name=${node_name:-SKYBYTE}-$kind
 node_port=$(ask "监听 TCP 端口 [$node_port]：" "TCP listen port [$node_port]: ") || return 1
 case $kind in xhttp-reality) node_port=${node_port:-443};; *) node_port=${node_port:-2053};; esac
  listen=$(ask '监听：1 IPv4  2 双栈 IPv4+IPv6 [1]：' 'Listen: 1 IPv4  2 Dual-stack IPv4+IPv6 [1]: ') || return 1
  case ${listen:-1} in 1) listen=0.0.0.0;; 2) listen=::;; *) return 1;; esac
  while :; do
   host=$(ask '客户端连接地址（必填：本 VPS 的公网 IP 或域名）：' 'Client connection address (required: this VPS public IP/domain): ') || return 1
   [[ $host =~ [^[:space:]] ]] && break
   warn '此项没有默认值，请填写本 VPS 的公网 IP 或域名。' 'There is no default; enter this VPS public IP or domain.'
  done
 helper preflight --port "$node_port" --listen "$listen" --address "$host" --name "$node_name" --kind "$kind" || return 1
 install_environment_check "$kind" && install_port_check "$node_port" "$listen" || return 1
 if [[ $kind == xhttp-tls ]]; then
  sni=$(ask '证书域名 / TLS SNI：' 'Certificate domain / TLS SNI: ') || return 1
  cert=$(ask '已有可信 fullchain 证书文件绝对路径：' 'Absolute path to trusted fullchain certificate: ') || return 1
  private_key=$(ask '私钥文件绝对路径（不修改源文件）：' 'Absolute private-key path (source is preserved): ') || return 1
  helper tls-input --sni "$sni" --cert "$cert" --key "$private_key" || return 1
  local cdn
    cdn=$(ask '通过 CDN 连接？[y/N]：' 'Use a CDN? [y/N]: ') || return 1
   if confirmed "$cdn"; then flags+=(--cdn); mode=packet-up; fi
  warn 'CDN 的 DNS、HTTPS 端口及回源 TLS 验证须在提供商后台配置。' 'Configure CDN DNS, supported HTTPS port and verified origin TLS at your provider.'
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
 apply_stage "$stage" yes || { error '安装失败，原配置已保留或回退。' 'Install failed; previous configuration retained or restored.'; return 1; }
 show_nodes
}
