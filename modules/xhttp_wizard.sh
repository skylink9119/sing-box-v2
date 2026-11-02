# Front-loaded XHTTP choices; no package, service or node changes before final y.
xhttp_guided_install() (
 local XHTTP_KIND=${1:-xhttp-reality} XHTTP_NAME XHTTP_SNI=addons.mozilla.org
 local XHTTP_CERT='' XHTTP_KEY='' XHTTP_CDN=0 WIZARD_CHOICE
 local selected_bbr selected_firewall selected_qr installed_kinds
 installed_kinds=''
 if [[ -f $BASE/xhttp/state.json || -L $BASE/xhttp/state.json ]];then installed_kinds=$(xhttp_backend node-kinds) || return 1;fi
 if grep -Fxq "$XHTTP_KIND" <<< "$installed_kinds";then err "$(L '所选 XHTTP 协议已经安装，请使用 b → 11 管理。' 'This XHTTP protocol is installed; manage it through b → 11.')";return 1;fi
 case $XHTTP_KIND in xhttp-reality|xhttp-tls);;*)return 1;;esac
 XHTTP_NAME=$(choose_node_name) || return 1
 if [[ $XHTTP_KIND == xhttp-tls ]];then
  prompt_read "$(L '证书域名 / TLS SNI：' 'Certificate domain / TLS SNI: ')" XHTTP_SNI || return 0
  prompt_read 'TLS fullchain: ' XHTTP_CERT || return 0
  prompt_read 'TLS private key: ' XHTTP_KEY || return 0
  xhttp_backend tls-input --sni "$XHTTP_SNI" --cert "$XHTTP_CERT" --key "$XHTTP_KEY" || return 1
  wizard_toggle "$(L '是否通过 CDN 连接（需自行配置 CDN）？' 'Connect through a separately configured CDN?')" || return 0;XHTTP_CDN=$WIZARD_CHOICE
 fi
 wizard_toggle "$(L '是否开启 BBR + FQ？' 'Enable BBR + FQ?')" || return 0;selected_bbr=$WIZARD_CHOICE
 wizard_toggle "$(L '是否安装并开启 UFW 防火墙？' 'Install and enable UFW?')" || return 0;selected_firewall=$WIZARD_CHOICE
 wizard_toggle "$(L '是否安装小火箭二维码工具？' 'Install Shadowrocket QR tooling?')" || return 0;selected_qr=$WIZARD_CHOICE
 say '========== XHTTP 自动部署计划 ==========' '========== Guided XHTTP deployment plan =========='
 say "节点：${XHTTP_NAME}；协议：$XHTTP_KIND" "Node: $XHTTP_NAME; protocol: $XHTTP_KIND"
 say '内核：按需下载官方最新稳定版 Xray；已有 Xray 核心复用，可单独更新。' 'Core: download latest official stable Xray on demand; reuse an existing core, with a separate update option.'
 if [[ $XHTTP_KIND == xhttp-reality ]];then
  say 'TCP 443；地址自动识别；addons.mozilla.org:443；随机路径；auto 模式。' 'TCP 443; automatic public address; addons.mozilla.org:443; random path; auto mode.'
 else
  say "TCP 2053；证书域名：${XHTTP_SNI}；随机路径；CDN：${XHTTP_CDN}。" "TCP 2053; certificate name: $XHTTP_SNI; random path; CDN: $XHTTP_CDN."
 fi
 say "BBR：$(wizard_selected "$selected_bbr")；UFW：$(wizard_selected "$selected_firewall")；二维码：$(wizard_selected "$selected_qr")" "BBR: $(wizard_selected "$selected_bbr"); UFW: $(wizard_selected "$selected_firewall"); QR: $(wizard_selected "$selected_qr")"
 [[ $selected_firewall != 1 ]] || detect_ssh_ports || return 1
 warn "$(L 'TCP 端口必须空闲；若 Reality 已占用 443，请取消并选 b → 11 → 12 自定义安装。XHTTP 不支持 Vision flow；请使用支持 XHTTP 的客户端。' 'The TCP port must be free. If Reality uses 443, cancel and choose b → 11 → 12 for custom installation. XHTTP has no Vision flow and requires a compatible client.')"
 confirm "$(L '按以上计划自动安装 XHTTP？' 'Automatically install XHTTP using this plan?')" || return 0
 xhttp_command guided || return 1
 deployment_apply_selected "$selected_bbr" "$selected_firewall" "$selected_qr" xhttp || warn "$(L 'XHTTP 节点已保留，部分所选配套未完成，请核对上方结果。' 'XHTTP node retained; some optional setup is incomplete. Inspect the results above.')"
)

xhttp_guided_select(){
 local choice
 prompt_options 'XHTTP 自动部署
1. XHTTP + Reality（默认）
2. XHTTP + TLS / CDN（需域名及可信证书）
0. 返回' 'Guided XHTTP deployment
1. XHTTP + Reality (default)
2. XHTTP + TLS / CDN (domain and trusted certificate required)
0. Back'
 while :;do
  prompt_read "$(L '选择 [1]：' 'Choose [1]: ')" choice || return 0
  case ${choice:-1} in
   1)xhttp_guided_install xhttp-reality;return $?;;
   2)xhttp_guided_install xhttp-tls;return $?;;
   0)return 0;;
   *)err "$(L '请输入 1、2 或 0' 'Enter 1, 2 or 0')";;
  esac
 done
}
