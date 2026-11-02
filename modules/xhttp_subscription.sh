# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
# lib/subscription.sh — build-time module; assembled by scripts/build.py.
show_nodes(){
 [[ -f $SKYBYTE_XRAY_DIR/state.json ]] || { warn '尚未安装节点。' 'No nodes installed.'; return 0; }
 local line nodes index=0
 nodes=$(helper show) || return 1
 warn '节点链接包含凭据，请勿公开。' 'Node links contain credentials; keep them private.'
 while IFS= read -r line; do
  if (( index % 2 == 0 )); then separator; printf '%s%s%s\n' "$YELLOW" "$line" "$RESET"
  else printf '%s%s%s\n' "$RED" "$line" "$RESET"; fi
  index=$((index + 1))
 done <<< "$nodes"
 separator
 warn "文件：$SKYBYTE_XRAY_DIR/nodes.txt、subscription-base64.txt、client-*.json" "Files: $SKYBYTE_XRAY_DIR/nodes.txt, subscription-base64.txt, client-*.json"
}
qr_nodes(){
 helper guard || return 1
 if ! command -v qrencode >/dev/null; then
  confirm '安装本地二维码工具？' 'Install local QR utility?' || return 1
  apt_refresh && apt-get install -y qrencode || return 1
 fi
 local uri
 while IFS= read -r uri; do [[ -z $uri ]] || { separator; printf '%s' "$uri" | qrencode -t ANSIUTF8 || return 1; }; done < "$SKYBYTE_XRAY_DIR/nodes.txt" || return 1
 warn 'XHTTP 扫码需要客户端本身支持 XHTTP；二维码不改变兼容性。' 'XHTTP QR import requires an XHTTP-capable client.'
}
