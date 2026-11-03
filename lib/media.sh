media_engine(){
 python3 - "$@" <<'PY_MEDIA'
# @include media.py
import sys
try: diagnostic_main(sys.argv[1:])
except (ValueError, OSError, subprocess.SubprocessError) as error:
 print('检测失败 / Diagnostic failed: '+safe_text(error), file=sys.stderr);sys.exit(1)
PY_MEDIA
}
quality_engine(){
 python3 - "$@" <<'PY_QUALITY'
# @include media.py
# @include quality.py
import sys
try: quality_main(sys.argv[1:])
except (ValueError, OSError, subprocess.SubprocessError) as error:
 print('检测未完成 / Diagnostic incomplete: '+safe_text(error), file=sys.stderr);sys.exit(1)
PY_QUALITY
}
media_check(){
 local selection action family=4 port=''
 if [[ $# == 0 || $1 == --menu || $1 == --interactive ]];then
  prompt_options '========== VPS 质量检测 ==========
【本机与公网 · xykt / NodeQuality 同源工具】
1. 硬件信息（快速查看）
2. IP 质量 / 流媒体（IPv4）
3. IP 质量 / 流媒体（IPv6）
4. 网络质量 / 三网测速
5. 三网回程 / 详细路由
6. 完整体检（硬件性能 + IP + 网络 + 回程）

【WARP · 流媒体与 AI】
7. WARP 代理出口检测
8. 直连 IPv4 / WARP 对比
0. 返回' '========== VPS quality diagnostics ==========
[Direct · xykt engines also used by NodeQuality]
1. Hardware information (quick)
2. IP quality / media (IPv4)
3. IP quality / media (IPv6)
4. Network quality / speed tests
5. Return routes / detailed traceroute
6. Full assessment (hardware + IP + network + routes)

[WARP · Media and AI]
7. WARP proxy egress
8. Direct IPv4 / WARP comparison
0. Back'
  [[ ${1:-} != --menu ]] || return 0
  prompt_read '> ' selection || return 0
 else selection=$1;fi
 case $selection in
  1)action=quick;;2)action=ip;;3)action=ip;family=6;;4)action=network;;5)action=route;;6)action=full;;
  7)action=warp;;8)action=compare;;0)return 0;;*)return 1;;
 esac
 if [[ $action == warp || $action == compare ]];then
  port=$(warp_engine port) && warp_loopback "$port" && warp_verify "$port" || return 1
  report_output media_engine "$action" "$REPORT" "${LANGUAGE_CHOICE:-zh_CN}" "$port"
  return
 fi
 case $action in
  network|route|full)
   prompt_read "$(L '检测网络 [4]（4 / 6）: ' 'Address family [4] (4 / 6): ')" family || return 0
   family=${family:-4};[[ $family == 4 || $family == 6 ]] || { err "$(L '请选择 4 或 6' 'Select 4 or 6')";return 1; };;
 esac
 say '按需下载并校验 xykt 官方脚本；可能安装检测依赖。仅保存本地 TXT/JSON，不上传报告、不生成 HTML。检测会访问第三方服务，结果不保证实际解锁。' 'Verified xykt scripts run on demand and may install diagnostic dependencies. Local TXT/JSON only; no report uploads or HTML. Probes contact third-party services and cannot guarantee playback.'
 say '隐私模式跳过 Geekbench；快速硬件查看不跑性能测试。完整体检会增加 CPU、内存和磁盘负载；测速会消耗流量。' 'Privacy mode skips Geekbench. Quick hardware mode skips benchmarks. Full assessment loads CPU, memory and disk; speed tests consume traffic.'
 confirm "$(L '开始检测？' 'Start diagnostics?')" || return 0
 ensure_binary curl curl || return 1
 report_output quality_engine "$action" "$REPORT" "${LANGUAGE_CHOICE:-zh_CN}" "$family"
}
