# lib/firewall.sh — build-time module; assembled by scripts/build.py.
firewall_audit(){
 if command -v ufw >/dev/null; then
  local rules hy2_port; rules=$(LC_ALL=C ufw status); printf '%s\n' "$rules"
  if [[ -f $META && $(protocol_mode) != 1 && $rules == *'Status: active'* ]]; then
   hy2_port=$(protocol_port hysteria2) || return 1
   grep -Eq "${hy2_port}/udp[[:space:]]+ALLOW" <<<"$rules" || warn "$(L "未检测到 UDP $hy2_port 放行，请检查规则" "UDP $hy2_port allow rule not detected; inspect rules")"
   if [[ $(state hop) == True ]]; then
    grep -F "$(state hop_start):$(state hop_end)/udp" <<<"$rules" | grep -q ALLOW || warn "$(L '未检测到跳跃 UDP 范围放行' 'Hopping UDP range allow rule not detected')"
   fi
  fi
 else warn "$(L '未安装 UFW；请检查 nftables 和云防火墙' 'UFW unavailable; inspect nftables and provider firewall')"; fi
 warn "$(L '云防火墙须在服务商控制台检查' 'Check provider firewall in the hosting console')"
}
initialize_server(){
 need_root
 if [[ ! -r $OS_RELEASE ]]; then err "$(L '无法识别操作系统' 'Cannot detect operating system')"; return 1; fi
 # shellcheck source=/dev/null
 . "$OS_RELEASE"
 case "${ID:-}" in
  ubuntu|debian) ;;
  *) err "$(L "只支持 Ubuntu/Debian，当前：${ID:-unknown}" "Ubuntu/Debian only; detected ${ID:-unknown}")"; return 1;;
 esac
 command -v apt-get >/dev/null || { err "$(L '缺少 apt-get' 'apt-get not found')"; return 1; }
 say "系统：${PRETTY_NAME:-$ID}" "System: ${PRETTY_NAME:-$ID}"
 say '默认仅安装基础依赖；系统升级和运维工具可单独选择。' 'Installs base dependencies by default; system upgrades and diagnostic tools are optional.'
 say '不会自动启用 UFW、变更 SSH、修改 BBR 或重启系统。' 'Does not enable UFW, change SSH/BBR, or reboot.'
 warn "$(L '升级可能更改内核、SSH 等软件包；建议先做 VPS 快照并保留控制台。' 'Updates may change kernel/SSH; create a snapshot and retain console access.')"
 confirm "$(L '确认执行新服务器初始化？' 'Initialize this server?')" || { say '已取消' Cancelled; return 0; }
 local upgrade=false
 local -a packages=(curl tar openssl ca-certificates ufw iproute2 python3 coreutils util-linux nftables procps)
 if confirm "$(L '同时升级已安装软件？' 'Also upgrade installed packages?')";then upgrade=true;fi
 if confirm "$(L '额外安装运维工具（vim、git、htop、mtr 等）？' 'Install optional tools (vim, git, htop, mtr, etc.)?')";then
  packages+=(wget nano vim unzip zip iputils-ping dnsutils traceroute mtr-tiny net-tools netcat-openbsd jq git socat lsof htop bc)
 fi
 # Installing chrony can remove timesyncd; keep an existing active time-sync service.
 if ! systemctl is-active --quiet chrony && ! systemctl is-active --quiet systemd-timesyncd && ! systemctl is-active --quiet ntp && ! systemctl is-active --quiet ntpsec; then packages+=(chrony); fi
 say '更新软件索引...' 'Updating package indexes...'
 apt_refresh || { err "$(L '软件索引更新失败' 'Package index update failed')"; return 1; }
 if [[ $upgrade == true ]];then
  say '升级已安装软件（不会自动执行 full-upgrade）...' 'Upgrading packages (not full-upgrade)...'
  DEBIAN_FRONTEND=noninteractive apt-get upgrade -y || { err "$(L '系统升级失败；请检查 apt/dpkg 状态' 'Upgrade failed; check apt/dpkg status')"; return 1; }
 fi
 say '安装基础工具...' 'Installing essential tools...'
 apt_install --no-install-recommends "${packages[@]}" || { err "$(L '工具安装失败' 'Tool installation failed')"; return 1; }
 say '检测时间同步服务...' 'Checking time synchronization...'
 if command -v timedatectl >/dev/null 2>&1; then timedatectl status --no-pager 2>/dev/null || :; fi
 # Do not forcibly disable an existing time-sync daemon.
 if systemctl is-active --quiet chrony 2>/dev/null; then
  say 'chrony 已运行。' 'chrony is running.'
 elif systemctl is-active --quiet systemd-timesyncd 2>/dev/null || systemctl is-active --quiet ntp 2>/dev/null || systemctl is-active --quiet ntpsec 2>/dev/null; then
  say '其他时间同步服务正在运行，不会强制切换到 chrony。' 'Another time synchronization service is running; not switching.'
 else
  say '尝试启用 chrony 时间同步...' 'Trying to enable chrony...'
  systemctl enable --now chrony 2>/dev/null || warn "$(L 'chrony 未启动，请人工检查' 'chrony did not start; check manually')"
 fi
 say '========== 只读检查 ==========' '========== Read-only checks =========='
 echo 'DNS github.com:'
 getent ahostsv4 github.com | sed -n '1,3p' || say 'DNS 解析失败' 'DNS resolution failed'
 say 'GitHub HTTPS:' 'GitHub HTTPS:'
 curl -4sS -I -L --connect-timeout 8 --max-time 18 -o /dev/null -w 'HTTP %{http_code}\n' https://github.com || warn "$(L 'HTTPS 无法连接' 'HTTPS connection failed')"
 say 'SSH 监听端口（仅查看）：' 'SSH listening ports (read-only):'
 ss -ltnp | grep -E 'sshd|:22[[:space:]]' || say '未识别 sshd 监听，请自行核实实际 SSH 端口' 'Could not identify sshd; verify actual SSH port'
 say 'UFW 状态（没有自动开启）：' 'UFW status (not enabled automatically):'
 ufw status verbose || :
 say '系统内核：' Kernel:
 uname -r
 say '如内核或关键服务已升级，请在维护窗口确认后自行决定是否重启。' 'If kernel or essential services were upgraded, plan a manual reboot if necessary.'
 say '新服务器初始化结束。' 'Server initialization complete.'
}

# UFW safety: never assume SSH port 22, and never bypass cloud firewall checks.
detect_ssh_ports(){
 local ports connection_port
 connection_port=$(awk '{print $4}' <<<"${SSH_CONNECTION:-}")
 ports=$(ss -H -lntp | awk '/sshd/ {n=split($4,a,":"); print a[n]}' | sort -nu)
 if [[ -z $ports ]] && command -v sshd >/dev/null; then ports=$(sshd -T 2>/dev/null | awk '$1=="port"{print $2}' | sort -nu); fi
 if valid_port "$connection_port"; then ports=$(printf '%s\n%s\n' "$ports" "$connection_port" | sed '/^$/d' | sort -nu); fi
 SSH_PORTS=$ports
 printf '%s\n' "$(L '识别到 SSH 端口（请确认）：' 'Detected SSH ports (verify): ')$ports"
}
firewall(){
 local choice port proto
 need_root
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 prompt_options '========== UFW 防火墙 ==========
1. 安装 UFW
2. 开启防火墙
3. 关闭防火墙
4. 查看状态
5. 放行端口
6. 删除规则
0. 返回上一层' '========== UFW firewall ==========
1. Install UFW
2. Enable firewall
3. Disable firewall
4. Show status
5. Allow a port
6. Delete a rule
0. Back one level'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return
 else
  choice=$1
 fi
 case "$choice" in
 1) if confirm "$(L '安装 UFW？' 'Install UFW?')"; then apt_install ufw ; fi;;
 2)
   require_cmd ufw || return
   say '当前 SSH 监听信息（必须人工核实）：' 'SSH listener information (VERIFY manually):'
   detect_ssh_ports
   prompt_read "$(L '输入当前 SSH TCP 端口（请核实云控制台/sshd 设置）：' 'Enter verified SSH TCP port: ')" port
   port=${port:-${SSH_PORTS:-}}
   valid_port "$port" || { err "$(L 'SSH 端口无效' 'Invalid SSH port')"; return 1; }
   warn "$(L '如果 SSH 端口判断错误，开启 UFW 可能导致远程连接断开！请保留 VPS 控制台访问。' 'Wrong SSH port may lock you out. Keep VPS console access.')"
   say '将放行 SSH 与实际节点、订阅和 HTTP证书验证端口。' 'Will allow SSH and actual node, subscription and HTTP certificate-validation ports.'
   confirm "$(L '确认开启 UFW 防火墙？' 'Enable UFW now?')" || return 0
   ufw allow "$port/tcp" || return 1
   local detected
   while read -r detected; do [[ -z $detected ]] || ufw allow "$detected/tcp" || return 1; done <<<"$SSH_PORTS"
   firewall_allow_protocols || return 1
   if [[ -f $META && $(state hop) == True ]]; then ufw allow "$(state hop_start):$(state hop_end)/udp" || return 1; fi
   ufw default deny incoming || return 1
   ufw default allow outgoing || return 1
   ufw --force enable || return 1
   warn "$(L '如有 HY2 跳跃或云防火墙，需另外确认规则。' 'Check HY2 hopping and provider firewall rules separately.')" ;;
 3) require_cmd ufw && if confirm "$(L '关闭 UFW 会降低保护，确定？' 'Disable UFW and reduce protection?')"; then ufw --force disable ; fi;;
 4) require_cmd ufw && report_output ufw status verbose ;;
 5) require_cmd ufw || return
    prompt_read "$(L '端口：' 'Port: ')" port; valid_port "$port" || return 1
    prompt_read "$(L '协议 (tcp/udp)：' 'Protocol (tcp/udp): ')" proto; [[ $proto == tcp || $proto == udp ]] || return 1
    if confirm "$(L "放行 $port/${proto}？" "Allow $port/$proto?")"; then ufw allow "$port/$proto" ; fi;;
 6) require_cmd ufw || return; ufw status numbered
    prompt_read "$(L '规则编号：' 'Rule number: ')" port; [[ $port =~ ^[0-9]+$ ]] || return 1
    if confirm "$(L '删除指定规则？确认不会影响 SSH！' 'Delete rule? Ensure SSH stays reachable!')"; then ufw --force delete "$port" ; fi;;
 0) return;; *) err "$(L '无效选择' 'Invalid choice')";;
 esac
}
