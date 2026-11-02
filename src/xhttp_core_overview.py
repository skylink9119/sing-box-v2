# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
def overview_read(path):
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return ""


def overview_command(arguments):
    """Best-effort local probes must never prevent opening the menu."""
    try:
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=2,
                                env={**os.environ, "LC_ALL": "C"})
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def overview_commands(commands):
    # All local probes share one short wait instead of stacking their timeouts.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = pool.map(overview_command, commands.values())
        return dict(zip(commands, results))


def startup_overview(root, binary, language="zh"):
    def tr(zh, en):
        return en if language == "en" else zh

    unknown = tr("未知", "Unknown")

    def clean(value):
        # Local host/package metadata is untrusted terminal text, too.
        value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", str(value))
        return " ".join("".join(c if c.isprintable() else " " for c in value).split())[:240] or unknown

    def gib(value):
        return f"{value / (1024 ** 3):.2f} GiB"

    os_name = unknown
    for line in overview_read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            try:
                os_name = " ".join(shlex.split(line.split("=", 1)[1])) or unknown
            except ValueError:
                pass
            break
    machine = platform.uname()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine.machine, machine.machine)
    cpu = next((line.split(":", 1)[1].strip() for line in overview_read("/proc/cpuinfo").splitlines()
                if line.split(":", 1)[0].strip() in ("model name", "Hardware", "Processor") and ":" in line), unknown)
    memory = {}
    for line in overview_read("/proc/meminfo").splitlines():
        match = re.fullmatch(r"(\w+):\s+(\d+) kB", line)
        if match:
            memory[match[1]] = int(match[2]) * 1024
    total = memory.get("MemTotal", 0)
    available = memory.get("MemAvailable", sum(memory.get(key, 0) for key in ("MemFree", "Buffers", "Cached")))
    used = max(0, total - min(total, available))
    memory_text = f"{gib(used)} / {gib(total)}" if total else unknown
    swap = memory.get("SwapTotal", 0)
    swap_text = f"{gib(max(0, swap - memory.get('SwapFree', 0)))} / {gib(swap)}" if swap else tr("未配置", "Not configured")
    try:
        disk = shutil.disk_usage("/")
        disk_text = f"{gib(disk.used)} / {gib(disk.total)} ({disk.used / disk.total:.0%})" if disk.total else unknown
    except OSError:
        disk_text = unknown
    try:
        minutes = int(float(overview_read("/proc/uptime").split()[0])) // 60
        uptime = tr(f"{minutes // 1440} 天 {minutes // 60 % 24} 小时 {minutes % 60} 分", f"{minutes // 1440}d {minutes // 60 % 24}h {minutes % 60}m")
    except (ValueError, IndexError):
        uptime = unknown
    load = " / ".join(overview_read("/proc/loadavg").split()[:3]) or unknown

    components = [("UFW", "ufw", "ufw.service"), ("firewalld", "firewall-cmd", "firewalld.service"),
                  (tr("WARP 客户端", "WARP client"), "warp-cli", "warp-svc.service"),
                  ("Fail2ban", "fail2ban-client", "fail2ban.service"), (tr("二维码工具", "QR utility"), "qrencode", None)]
    present = {tool: bool(shutil.which(tool)) for _, tool, _ in components}
    units = ["skybyte-xray.service", *[unit for _, tool, unit in components if unit and present[tool]]]
    core_installed = False
    core_version = tr("未安装", "Not installed")
    try:
        checked_path(binary)
        marker = checked_path(binary.parent / ".owner")
        core_installed = binary.is_file() and os.access(binary, os.X_OK) and marker.read_text() == OWNER
    except (OSError, ValueError):
        pass
    commands = {"services": ["systemctl", "show", "--no-pager", "--property=Id,LoadState,ActiveState,UnitFileState", *units]}
    if core_installed:
        commands["version"] = [str(binary), "version"]
    if present["ufw"]:
        commands["ufw"] = ["ufw", "status"]
    readings = overview_commands(commands)
    service_output = readings["services"]
    services = {}
    for block in service_output.split("\n\n"):
        properties = dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        if properties.get("Id") in units:
            services[properties["Id"]] = properties

    def service_status(unit, installed):
        properties = services.get(unit, {})
        active = properties.get("ActiveState")
        if active in ("active", "reloading"):
            return tr("运行中", "Running")
        if active == "failed":
            return tr("运行失败", "Failed")
        if active in ("activating", "deactivating"):
            return tr("启动中" if active == "activating" else "停止中", "Starting" if active == "activating" else "Stopping")
        if properties.get("LoadState") == "not-found":
            return tr("已安装，服务未注册", "Installed, service not registered") if installed else tr("未安装", "Not installed")
        if active == "inactive":
            return tr("已安装，未运行", "Installed, inactive")
        return tr("已安装，状态未知", "Installed, status unknown") if installed else unknown

    if core_installed:
        version_output = readings["version"]
        match = re.search(r"^Xray\s+(\S+)", version_output)
        core_version = match[1] if match else unknown
    main_service = services.get("skybyte-xray.service", {})
    enabled = main_service.get("UnitFileState", "")
    boot = tr("已启用", "Enabled") if enabled in ("enabled", "enabled-runtime") else (
        tr("未启用", "Disabled") if enabled in ("disabled", "masked", "masked-runtime", "static", "indirect") else unknown)

    nodes = tr("尚未安装节点", "No nodes installed")
    warp_text = tr("未启用分流", "Routing disabled")
    try:
        checked_path(root)
        if root.exists():
            ensure_owned(root)
            state = load_state(root)
            if "warp" in state:
                warp_text = tr("已配置域名分流", "Domain routing configured") + f" | 127.0.0.1:{state['warp']['port']} | {len(state['warp']['domains'])} " + tr("个后缀（连通性见菜单 n）", "suffixes (test connectivity in menu n)")
            names = {"vision": "Reality + Vision", "xhttp-reality": "XHTTP + Reality", "xhttp-tls": "XHTTP + TLS/CDN"}
            nodes = " | ".join(f"{names[kind]}: TCP {node['port']}" for kind, node in state["nodes"].items()) or nodes
    except (OSError, ValueError, KeyError, TypeError):
        nodes = tr("配置读取失败，请检查服务与日志", "Configuration unreadable; check service and logs")

    algorithm = overview_read("/proc/sys/net/ipv4/tcp_congestion_control").strip()
    qdisc = overview_read("/proc/sys/net/core/default_qdisc").strip()
    bbr = tr("已开启 BBR 加速", "BBR acceleration enabled") if algorithm == "bbr" else (
        tr("未开启 BBR 加速", "BBR acceleration not enabled") if algorithm else unknown)
    if algorithm:
        bbr += f" ({algorithm}" + (f" / {qdisc}" if qdisc else "") + ")"
    statuses = []
    for label, tool, unit in components:
        if not present[tool]:
            status = tr("未安装", "Not installed")
        elif tool == "ufw":
            ufw = readings["ufw"]
            status = tr("已启用", "Enabled") if ufw.startswith("Status: active") else (
                tr("已安装，未启用", "Installed, disabled") if ufw.startswith("Status: inactive") else tr("已安装，状态未知", "Installed, status unknown"))
        else:
            status = service_status(unit, True) if unit else tr("已安装", "Installed")
        statuses.append(f"{label}: {status}")
    lines = [tr("服务器配置", "Server configuration"),
             f"  {tr('系统', 'OS')}: {os_name} | {tr('架构', 'Architecture')}: {arch}",
             f"  {tr('内核', 'Kernel')}: {machine.release}",
             f"  CPU: {cpu} ({os.cpu_count() or unknown} vCPU)",
             f"  {tr('内存', 'Memory')}: {memory_text} | Swap: {swap_text}",
             f"  {tr('根分区', 'Root disk')}: {disk_text}",
             f"  {tr('运行时间', 'Uptime')}: {uptime} | {tr('负载 (1/5/15 分)', 'Load (1/5/15 min)')}: {load}",
             tr("运行状态", "Runtime status"),
             f"  Xray: {service_status('skybyte-xray.service', core_installed)} | {tr('开机自启', 'Start on boot')}: {boot}",
             f"  {tr('实际核心版本', 'Installed core version')}: {core_version}",
             f"  {tr('节点', 'Nodes')}: {nodes}",
             f"  BBR: {bbr}",
             f"  WARP: {warp_text}",
             tr("插件/组件（系统检测）", "Plugins/components (system detection)"),
             "  " + " | ".join(statuses[:2]), "  " + " | ".join(statuses[2:])]
    return "\n".join(clean(line) if not line.startswith("  ") else "  " + clean(line) for line in lines)
