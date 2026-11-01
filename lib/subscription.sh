# lib/subscription.sh — build-time module; assembled by scripts/build.py.
# @include lib/subscription_exports.sh
shadowrocket_qr(){
 check_owned || return 1
 if ! command -v qrencode >/dev/null; then
  say '安装二维码工具 qrencode...' 'Installing qrencode...'
  apt_install qrencode || return 1
 fi
 exports >/dev/null || return 1
 warn "$(L '二维码包含节点凭据，请勿公开。HY2 自签名节点仍需配置信任证书。' 'QR codes contain node credentials; keep them private. Self-signed HY2 still requires certificate trust.')"
 local link name count=0
 while IFS= read -r link; do
  [[ -n $link ]] || continue
  name=$(printf '%s' "$link" | python3 -c 'import sys,urllib.parse; u=urllib.parse.urlsplit(sys.stdin.read()); print(urllib.parse.unquote(u.fragment) if u.fragment else dict(urllib.parse.parse_qsl(u.query)).get("remarks","Shadowrocket"))') || return 1
  printf '%s\n' '----------------------------------------------'
  printf '%s%s%s\n' "$YELLOW" "$name" "$RESET"
  # Feed credentials via stdin; keep the QR high-contrast for phone cameras.
  printf '%s' "$link" | qrencode -t ANSIUTF8 -m 2 || return 1
  count=$((count+1))
 done < "$BASE/shadowrocket-native-nodes.txt"
 printf '%s\n' '----------------------------------------------'
 (( count > 0 )) || { err "$(L '没有可生成二维码的节点' 'No nodes available for QR codes')"; return 1; }
}

subscription(){
 check_owned || return
 warn "$(L '仅生成本地订阅文件；不会开启公开的 HTTP/HTTPS 订阅服务。' 'Local subscription files only; no public HTTP/HTTPS service will be started.')"
 exports || return 1
 say '已生成各客户端格式；请核实自签名信任。本地订阅文件不等于在线订阅网址。' 'Client formats exported; verify self-signed trust. Local subscription files are not hosted URLs.'
}

