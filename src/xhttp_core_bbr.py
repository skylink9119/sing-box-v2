# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
BBR_VALUES = {"net.core.default_qdisc": "fq", "net.ipv4.tcp_congestion_control": "bbr"}
BBR_MARK = "# SKYBYTE Xray Manager BBR v1\n"
BBR_PATH = Path("/etc/sysctl.d/90-skybyte-xray-bbr.conf")


def network_values():
    result = {}
    for setting in BBR_VALUES:
        value = system_command(["sysctl", "-n", setting]).stdout.strip()
        if not re.fullmatch(r"[A-Za-z0-9_]+", value):
            raise ValueError("Invalid kernel network value / 内核网络参数无效")
        result[setting] = value
    return result


def bbr_content(previous):
    if set(previous) != set(BBR_VALUES) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_]+", v) for v in previous.values()):
        raise ValueError("Invalid saved network settings / 原网络设置无效")
    return BBR_MARK + "# previous: " + json.dumps(previous, sort_keys=True) + "\n" + "".join(k + " = " + v + "\n" for k, v in BBR_VALUES.items())


def bbr_previous(path):
    checked_path(path)
    if not path.exists():
        return None
    text = path.read_text()
    if not text.startswith(BBR_MARK + "# previous: "):
        raise ValueError("Existing BBR file is not owned / 已有 BBR 配置不属于本脚本")
    previous = json.loads(text.splitlines()[1].removeprefix("# previous: "))
    if text != bbr_content(previous):
        raise ValueError("BBR file was edited; restore it before continuing / BBR 配置已被修改，请先核对恢复")
    return previous


def write_network_values(values):
    for setting, value in values.items():
        system_command(["sysctl", "-w", setting + "=" + value])
    if network_values() != values:
        raise ValueError("Kernel settings did not take effect / 内核设置未生效")


def rollback_network_values(values):
    # Attempt both settings even when one cannot be restored.
    failed = False
    for setting, value in values.items():
        try:
            system_command(["sysctl", "-w", setting + "=" + value])
        except (OSError, subprocess.SubprocessError):
            failed = True
    return not failed and network_values() == values


def bbr_change(enable, path=BBR_PATH):
    path = checked_path(path)
    previous = bbr_previous(path)
    current = network_values()
    if enable:
        available = system_command(["sysctl", "-n", "net.ipv4.tcp_available_congestion_control"]).stdout.split()
        if "bbr" not in available:
            if shutil.which("modprobe"):
                system_command(["modprobe", "tcp_bbr"], check=False)
            available = system_command(["sysctl", "-n", "net.ipv4.tcp_available_congestion_control"]).stdout.split()
        if "bbr" not in available:
            raise ValueError("Kernel does not provide BBR; no kernel upgrade performed / 当前内核不支持 BBR；未更换内核")
        if shutil.which("modprobe"):
            system_command(["modprobe", "sch_fq"], check=False)
        old_file = path.read_text() if previous is not None else None
        # Persist original values before touching the runtime, for recovery after interruption.
        write_private(path, bbr_content(previous if previous is not None else current), 0o644)
        target = BBR_VALUES
    else:
        if previous is None:
            raise ValueError("No managed BBR settings to restore / 没有本脚本管理的 BBR 设置可恢复")
        old_file = path.read_text()
        target = previous
    try:
        write_network_values(target)
        if not enable:
            path.unlink()
    except BaseException as error:
        try:
            restored = rollback_network_values(current)
        except (OSError, ValueError, subprocess.SubprocessError):
            restored = False
        if not restored:
            raise ValueError("Network rollback incomplete; saved BBR file retained for recovery / 网络参数回退未完成，已保留 BBR 文件，请检查 sysctl") from error
        if old_file is None:
            path.unlink()
        else:
            write_private(path, old_file, 0o644)
        raise
