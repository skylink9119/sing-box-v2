# Front-load guided choices; no package or node mutation before final consent.
wizard_toggle(){
 local answer
 while :;do
  prompt_read "$1 [y/N]: " answer || return 1
  if [[ $answer =~ ^[[:space:]]*[Yy][[:space:]]*$ ]];then WIZARD_CHOICE=1;return 0;fi
  if [[ $answer =~ ^[[:space:]]*([Nn])?[[:space:]]*$ ]];then WIZARD_CHOICE=0;return 0;fi
  err "$(L '请输入 y 或 n' 'Enter y or n')"
 done
}
wizard_protocol(){
 prompt_options '安装协议：
1. Reality + Vision（TCP）
2. Hysteria2（UDP）
3. 双协议
0. 返回' 'Protocol:
1. Reality + Vision (TCP)
2. Hysteria2 (UDP)
3. Both
0. Back'
 prompt_read '> ' WIZARD_PROTOCOL || return 1
 case $WIZARD_PROTOCOL in 0) return 2;;1|2|3)return 0;;*)err "$(L '无效协议选项' 'Invalid protocol')";return 1;;esac
}
wizard_selected(){
 if [[ $1 == 1 ]];then L '启用' 'Enable';else L '跳过' 'Skip';fi
}
guided_install() (
 local protocol_label install_kind=guided suffix=''
 if [[ ${2:-} == ipv6 ]];then install_kind='guided-ipv6';suffix=-IPv6;fi
 local WIZARD_PROTOCOL=${1:-} WIZARD_NODE_NAME WIZARD_BBR WIZARD_FIREWALL WIZARD_QR WIZARD_CHOICE
 if [[ -z $WIZARD_PROTOCOL ]];then
  if wizard_protocol;then :;else [[ $? == 2 ]] && return 0;return 1;fi
 fi
 [[ $WIZARD_PROTOCOL =~ ^[123]$ ]] || return 1
 WIZARD_NODE_NAME=$(choose_node_name "$suffix") || return 1
 wizard_toggle "$(L '是否开启 BBR + FQ（仅作用于 TCP）？' 'Enable BBR + FQ (TCP only)?')" || return 0;WIZARD_BBR=$WIZARD_CHOICE
 wizard_toggle "$(L '是否安装并开启 UFW 防火墙？' 'Install and enable UFW?')" || return 0;WIZARD_FIREWALL=$WIZARD_CHOICE
 wizard_toggle "$(L '是否安装小火箭二维码工具？' 'Install Shadowrocket QR tooling?')" || return 0;WIZARD_QR=$WIZARD_CHOICE
 case $WIZARD_PROTOCOL in
  1)protocol_label='Reality + Vision';;2)protocol_label=Hysteria2;;3)protocol_label=$(L 'Reality + HY2 双协议' 'Reality + HY2');;
 esac
 notice
 say '========== 自动部署计划 ==========' '========== Guided deployment plan =========='
 say "协议：${protocol_label}；节点：$WIZARD_NODE_NAME" "Protocol: $protocol_label; node: $WIZARD_NODE_NAME"
 if [[ -n ${SKYBYTE_ASSET_DIR:-} ]];then
  say "内核：离线官方安装包 $CORE_RECOMMENDED" "Core: offline official package $CORE_RECOMMENDED"
 else say '内核：安装时获取官方最新稳定版（不含预发布版）' 'Core: latest official stable release, resolved during installation (no prereleases)';fi
 if [[ $install_kind == guided-ipv6 ]];then
  say 'TCP 端口：443；自动使用首个通过检测的本机原生公网 IPv6，监听 IPv6/双栈。客户端须支持 IPv6。' 'TCP port: 443; use the first validated native public IPv6 with an IPv6/dual-stack listener. Client IPv6 required.'
 else say '端口：所选协议均为 443；公网地址自动识别。' 'Port: 443 for selected protocols; public address detected automatically.';fi
 if [[ $WIZARD_PROTOCOL != 2 ]];then say 'Reality 握手网站：addons.mozilla.org（安装前检测）' 'Reality target: addons.mozilla.org (checked before installation)';fi
 if [[ $WIZARD_PROTOCOL != 1 ]];then say 'HY2：自动自签证书，客户端须导入并验证；IPv4 跳跃默认 20000–30000/UDP，冲突时跳过并提示。' 'HY2: self-signed certificate requiring client trust; IPv4 hopping defaults to UDP 20000–30000, with conflicts reported.';fi
 say "BBR + FQ：$(wizard_selected "$WIZARD_BBR")" "BBR + FQ: $(wizard_selected "$WIZARD_BBR")"
 say "UFW：$(wizard_selected "$WIZARD_FIREWALL")" "UFW: $(wizard_selected "$WIZARD_FIREWALL")"
 say "二维码工具：$(wizard_selected "$WIZARD_QR")" "QR tool: $(wizard_selected "$WIZARD_QR")"
 if [[ $WIZARD_FIREWALL == 1 ]];then detect_ssh_ports || return 1;fi
 say '需要修改端口、连接地址、证书或握手网站，请取消后选 a → 9 自定义安装。' 'For custom ports, address, certificates or Reality target, cancel and choose a → 9.'
 confirm "$(L '同意声明并按以上计划开始自动安装？' 'Accept the notice and install using this plan?')" || return 0
 install_protocol "$WIZARD_PROTOCOL" "$install_kind"
)
manual_install(){
 local WIZARD_PROTOCOL
 if wizard_protocol;then install_protocol "$WIZARD_PROTOCOL" custom
 else [[ $? == 2 ]] && return 0;return 1;fi
}
