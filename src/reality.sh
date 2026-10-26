reality_engine(){ python3 - "$@" <<'PY_REALITY'
# @include reality.py
PY_REALITY
}
reality_menu(){
 local choice target sni
 if [[ $# == 0 || $1 == --menu ]];then
  prompt_options 'Reality 握手网站检测
1. 检测当前节点的握手网站
2. 检测自定义网站
0. 返回' 'Reality handshake target checks
1. Check configured Reality targets
2. Check a custom target
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
  0) return 0;; *) return 1;;
 esac
}
