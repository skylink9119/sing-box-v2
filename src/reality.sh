reality_engine(){ python3 - "$@" <<'PY_REALITY'
# @include reality.py
PY_REALITY
}
reality_replace(){
 local current choice sni target normalized host number
 current=$(reality_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --config "$CONF" --list) || return 1
 [[ -n $current ]] || { warn "$(L '未安装 Reality 节点，无需更换；可选择检测自定义网站。' 'No Reality node installed; use a custom target check instead.')";return 0; }
 printf '%s\n%s\n' "$(L '当前握手目标 / SNI：' 'Current target / SNI:')" "$current"
 prompt_options '选择新握手网站（回车选 1）：
1 Mozilla     addons.mozilla.org
2 Microsoft   www.microsoft.com
3 Apple       www.apple.com
4 Amazon      www.amazon.com
5 Cloudflare  www.cloudflare.com
6 Google      dl.google.com
7 自定义域名
0 返回' 'New handshake site (Enter selects 1):
1 Mozilla     addons.mozilla.org
2 Microsoft   www.microsoft.com
3 Apple       www.apple.com
4 Amazon      www.amazon.com
5 Cloudflare  www.cloudflare.com
6 Google      dl.google.com
7 Custom domain
0 Back'
 prompt_read '> ' choice || return 0
 case ${choice:-1} in
  1) sni=addons.mozilla.org;;2) sni=www.microsoft.com;;3) sni=www.apple.com;;
  4) sni=www.amazon.com;;5) sni=www.cloudflare.com;;6) sni=dl.google.com;;
  7) prompt_read 'Reality SNI: ' sni || return 0;;0) return 0;;*) return 1;;
 esac
 [[ -n $sni && $sni != 0 ]] || return 0
 prompt_read "$(L "握手目标 [$sni:443]（0 返回）：" "Handshake target [$sni:443] (0 to return): ")" target || return 0
 [[ $target != 0 ]] || return 0
 target=${target:-$sni:443}
 normalized=$(reality_engine --project sing-box --target "$target" --sni "$sni" --normalize) || return 1
 IFS=$'\t' read -r host number sni <<< "$normalized"
 if ! reality_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --target "$target" --sni "$sni";then
  err "$(L '新目标检测未通过，保留原配置。' 'New target failed checks; original configuration retained.')";return 1
 fi
 warn "$(L '更换会短暂重启正在运行的服务；保留 UUID、密钥及端口。所有 Reality 客户端需重新导入更新后的节点。' 'Running services will briefly restart; UUIDs, keys and ports are retained. Re-import updated nodes on all Reality clients.')"
 confirm "$(L '将管理员及受限用户的 Reality 握手网站更换为上述目标？' 'Apply this target to administrator and quota-managed Reality nodes?')" || return 0
 configuration_apply reality "$sni" "$host" "$number" || return 1
 ok "$(L 'Reality 握手网站已更换；请重新导入节点或更新客户端 SNI。' 'Reality target updated; re-import nodes or update client SNI.')"
}
reality_menu(){
 local choice target sni
 if [[ $# == 0 || $1 == --menu ]];then
  prompt_options 'Reality 握手网站检测
1. 检测当前节点的握手网站
2. 检测自定义网站
3. 更换握手网站（先检测后应用）
0. 返回' 'Reality handshake target checks
1. Check configured Reality targets
2. Check a custom target
3. Change handshake target (check before applying)
0. Back'
  [[ ${1:-} != --menu ]] || return 0
  prompt_read '> ' choice || return 0
 else choice=$1;fi
 case $choice in
  1) reality_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --config "$CONF";;
  2) prompt_read "$(L '握手目标（域名或 域名:端口，0 返回）：' 'Target (hostname or host:port, 0 to return): ')" target || return 0
     [[ $target != 0 ]] || return 0
     [[ -n $target ]] || { err "$(L '请填写握手目标' 'Enter a target')";return 1; }
     prompt_read "$(L '握手域名 / SNI（回车使用目标域名）：' 'Handshake SNI (Enter uses target hostname): ')" sni || return 0
     reality_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --target "$target" --sni "$sni";;
  3) reality_replace;;
  0) return 0;; *) return 1;;
 esac
}
