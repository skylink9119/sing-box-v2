# modules/reality.sh — build-time module; assembled by scripts/build.py.
choose_reality_sni(){
 local choice selected
 menu 'Reality 握手域名\n1 Microsoft  www.microsoft.com（默认）\n2 Apple      www.apple.com\n3 Amazon     www.amazon.com\n4 Cloudflare www.cloudflare.com\n5 Google     dl.google.com\n6 自定义域名\n0 返回' 'Reality handshake name\n1 Microsoft  www.microsoft.com (default)\n2 Apple      www.apple.com\n3 Amazon     www.amazon.com\n4 Cloudflare www.cloudflare.com\n5 Google     dl.google.com\n6 Custom domain\n0 Back' >&2
 while :; do
  choice=$(ask '选择 [1]（也可直接输入域名）：' 'Choose [1] (or enter a domain directly): ') || return 1
  case ${choice:-1} in
   1) selected=www.microsoft.com;;
   2) selected=www.apple.com;;
   3) selected=www.amazon.com;;
   4) selected=www.cloudflare.com;;
   5) selected=dl.google.com;;
   6) while :; do
       selected=$(ask '自定义 Reality 握手域名（必填）：' 'Custom Reality handshake domain (required): ') || return 1
       [[ $selected =~ [^[:space:]] ]] && break
       warn '请填写握手域名。' 'Enter a handshake domain.' >&2
      done;;
   0) return 0;;
   *) if [[ $choice =~ ^[0-9]+$ ]]; then
       warn '选项无效，请输入 1–6、0 或域名。' 'Invalid option; enter 1–6, 0 or a domain.' >&2
       continue
      fi
      selected=$choice;;
  esac
  printf '%s\n' "$selected"
  return 0
 done
}
