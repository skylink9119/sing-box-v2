media_check(){
 require_cmd curl && require_cmd python3 || return 1
 local selection paths port=''
 say '识别匿名页面中的地区字段、页面区域提示和明确地区限制；不登录账号、不验证订阅资格或实际播放。HTTP 200 仅表示页面有响应。' 'Reads region fields, page locale hints and explicit location restrictions from anonymous pages. No account login, subscription check or playback test; HTTP 200 only means the page responded.'
 prompt_options '1. 直连 IPv4
2. 直连 IPv6
3. 两者
4. WARP
5. IPv4 与 WARP 对比
0. 返回' '1. Direct IPv4
2. Direct IPv6
3. Both
4. WARP
5. IPv4/WARP comparison
0. Back'
 prompt_read '> ' selection || return 0
 case $selection in 1) paths=4;; 2) paths=6;; 3) paths=4,6;; 4) paths=warp;; 5) paths=4,warp;; 0) return 0;; *) return 1;; esac
 if [[ $paths == *warp* ]]; then port=$(warp_engine port) && warp_verify "$port" || return 1; fi
 python3 - "$paths" "$REPORT" "$port" "${LANGUAGE_CHOICE:-zh_CN}" <<'PY_MEDIA'
# @include media.py
PY_MEDIA
}
