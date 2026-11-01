# lib/traffic.sh — build-time module; assembled by scripts/build.py.
traffic(){
 local x
 report_output say 'vnStat 统计 VPS 网卡流量，不能区分 Reality/HY2；历史数据从安装后开始。' 'vnStat tracks VPS interface traffic, NOT Reality/HY2 separately. History starts when installed.'
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 prompt_options '1. 安装 vnStat
2. 今日
3. 本月
4. 实时网速
5. 历史汇总
0. 返回' '1. Install vnStat
2. Today
3. Monthly
4. Live
5. History
0. Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' x || return
 else
  x=$1
 fi
 case "$x" in
 1) if confirm "$(L '安装 vnStat？' 'Install vnStat?')"; then apt_install vnstat && systemctl enable --now vnstat; fi;;
 2) require_cmd vnstat && report_output vnstat -d;; 3) require_cmd vnstat && report_output vnstat -m;;
 4) require_cmd vnstat && report_output vnstat -l;; 5) require_cmd vnstat && report_output vnstat;; 0) return;; *) err "$(L '无效选择' 'Invalid choice')";; esac
}
