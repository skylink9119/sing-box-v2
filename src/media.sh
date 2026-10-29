media_engine(){
 python3 - "$@" <<'PY_MEDIA'
# @include media.py
import sys
try: diagnostic_main(sys.argv[1:])
except (ValueError, OSError, subprocess.SubprocessError) as error:
 print('检测失败 / Diagnostic failed: '+safe_text(error), file=sys.stderr);sys.exit(1)
PY_MEDIA
}
media_check(){
 local selection action port=''
 if [[ $# == 0 || $1 == --menu || $1 == --interactive ]];then
  prompt_options '========== 专业网络检测 ==========
【流媒体与 AI · UnlockTests】
1. VPS 直连 IPv4（全球 + AI）
2. VPS 直连 IPv6（全球 + AI）
3. VPS 直连双栈
4. WARP 代理出口
5. 直连 IPv4 / WARP 对比
6. 全地区平台（VPS IPv4）

【线路与测速 · 融合怪 Go】
7. 三网回程 / 路由
8. 三网测速（消耗流量）
9. 综合网络测评（消耗流量）
0. 返回' '========== Professional diagnostics ==========
[Media and AI · UnlockTests]
1. VPS direct IPv4 (global + AI)
2. VPS direct IPv6 (global + AI)
3. VPS direct dual stack
4. WARP proxy egress
5. Direct IPv4 / WARP comparison
6. All-region platforms (VPS IPv4)

[Routes and speed · goecs]
7. Return routes / traceroute
8. Speed tests (uses bandwidth)
9. Comprehensive network tests (uses bandwidth)
0. Back'
  [[ ${1:-} != --menu ]] || return 0
  prompt_read '> ' selection || return 0
 else selection=$1;fi
 case $selection in
  1)action=4;;2)action=6;;3)action=both;;4)action=warp;;5)action=compare;;6)action=all;;
  7)action=route;;8)action=speed;;9)action=full;;0)return 0;;*)return 1;;
 esac
 say '首次按需下载官方检测工具并校验；报告仅在本机，综合检测关闭上传。结果不保证账号可用或实际播放。' 'Official tools are downloaded and verified on demand; reports stay local and benchmark uploads are disabled. Results do not guarantee playback or account access.'
 case $action in
  warp|compare)port=$(warp_engine port) && warp_loopback "$port" && warp_verify "$port" || return 1;;
  speed|full)confirm "$(L '测速可能消耗大量流量并临时占用带宽，继续？' 'Tests may use substantial traffic and bandwidth. Continue?')" || return 0;;
 esac
 media_engine "$action" "$REPORT" "${LANGUAGE_CHOICE:-zh_CN}" "$port"
}
