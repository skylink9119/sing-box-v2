# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["port-numbers", "stage-ports", "purge-plan", "purge", "selfcheck", "overview", "warp-prepare", "warp-check", "warp-profile", "warp-status", "prepare", "commit", "rollback", "finalize", "backup", "restore",
                                            "ipv6-prepare", "remove", "rename", "edit", "reality-edit", "reality-targets", "refresh-tls", "show", "parameters", "guard", "download", "probe", "reality-input", "tls-input", "journal", "preflight", "node-kinds", "node-port", "node-ports", "firewall-status", "firewall-allow", "bbr-status", "bbr-enable", "bbr-restore", "manager-latest", "manager-update", "firewall-setup-check", "firewall-setup-plan", "firewall-setup", "ufw-state", "ufw-disable", "ufw-remove-plan", "ufw-package-state"])
    parser.add_argument("--root", default=os.environ.get("SKYBYTE_XRAY_DIR", "/etc/skybyte-xray"))
    parser.add_argument("--binary", default=os.environ.get("SKYBYTE_XRAY_BINARY", "/usr/local/lib/skybyte-xray/xray"))
    parser.add_argument("--unit", default=os.environ.get("SKYBYTE_XRAY_UNIT", "/etc/systemd/system/skybyte-xray.service"))
    parser.add_argument("--kind", choices=KINDS)
    parser.add_argument("--port", default=None)
    parser.add_argument("--listen", choices=["0.0.0.0", "::", "127.0.0.1", "::1"], default="0.0.0.0")
    parser.add_argument("--address", default=None)
    parser.add_argument("--sni", default="www.microsoft.com")
    parser.add_argument("--target", default="www.microsoft.com:443")
    parser.add_argument("--name", default="SKYBYTE")
    parser.add_argument("--path", default=None)
    parser.add_argument("--mode", choices=MODES, default="auto")
    parser.add_argument("--cert", default="")
    parser.add_argument("--key", default="")
    parser.add_argument("--ca-file", default=None)
    parser.add_argument("--cdn", action="store_true")
    parser.add_argument("--stage", default="")
    parser.add_argument("--file", default="")
    parser.add_argument("--active", action="store_true")
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--asset", default="Xray-linux-64.zip")
    parser.add_argument("--tag", default=CORE_VERSION)
    parser.add_argument("--ports", nargs="+", default=[])
    parser.add_argument("--zone", default="")
    parser.add_argument("--release", default="")
    parser.add_argument("--ssh-ports", nargs="+", default=[])
    parser.add_argument("--purge", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--language", choices=["zh", "en"], default="zh")
    parser.add_argument("--proxy-port", type=int, default=40000)
    parser.add_argument("--domains", nargs="+", default=[])
    parser.add_argument("--profile", choices=["all", *WARP_PROFILES], default="all")
    parser.add_argument("--disable", action="store_true")
    options = parser.parse_args()
    if options.command == "parameters":
        print(node_parameters(checked_path(options.root), options.language))
        return
    if options.command == "overview":
        print(startup_overview(Path(options.root), Path(options.binary), options.language))
        return
    if options.command == "warp-profile":
        print(" ".join(WARP_PROFILES[options.profile] if options.profile != "all" else sum(WARP_PROFILES.values(), [])))
        return
    if options.command == "warp-check":
        ip, country = warp_verify(options.proxy_port)
        print(f"WARP 出口已验证 / WARP egress verified: {ip} ({country})")
        return
    if options.command == "warp-status":
        print(warp_status(Path(options.root), options.language))
        return
    if options.command != "edit":
        options.port = options.port if options.port is not None else "443"
        options.address = options.address if options.address is not None else ""
        options.path = options.path if options.path is not None else ""
    if options.command == "ufw-state":
        print(ufw_state())
        return
    if options.command == "ufw-disable":
        print(ufw_disable())
        return
    if options.command == "ufw-package-state":
        print(ufw_package_state())
        return
    if options.command == "ufw-remove-plan":
        print(ufw_remove_plan(options.purge))
        return
    if options.command == "firewall-setup-check":
        if firewall_setup_check():
            print("Compatible Fail2ban TCP bans detected; will preserve them / 检测到可共存的独立 Fail2ban TCP 封禁，将保留现有防护与封禁地址")
        return
    if options.command == "firewall-setup-plan":
        ssh, others = firewall_setup_plan(Path(options.root), options.ssh_ports, options.ports)
        print("SSH TCP: " + ", ".join(map(str, ssh)))
        print("Other TCP / 其他 TCP: " + (", ".join(map(str, others)) or "none / 无"))
        return
    if options.command == "firewall-setup":
        if firewall_setup(Path(options.root), options.ssh_ports, options.ports):
            print("Fail2ban structure preserved; existing bans still apply / 已核对原有 Fail2ban 封禁结构仍在；已有封禁仍可能阻止连接")
        return
    if options.command == "manager-latest":
        tag = manager_release()["tag_name"]
        if manager_version(tag) > manager_version("v" + VERSION):
            print(tag)
        return
    if options.command == "manager-update":
        manager_update(checked_path(options.file), options.release)
        return
    if options.command in ("port-numbers", "node-ports", "node-port", "node-kinds"):
        root = checked_path(options.root)
        ensure_owned(root)
        nodes = load_state(root)["nodes"]
        if options.command == "port-numbers":
            for number in sorted({node["port"] for node in nodes.values()}):print(number)
            return
        if options.command == "node-port":
            if options.kind not in nodes:
                raise ValueError("该协议尚未安装 / Protocol not installed")
            print(nodes[options.kind]["port"])
            return
        if not nodes:
            raise ValueError("No nodes installed / 尚未安装节点")
        if options.command == "node-kinds":
            print("\n".join(nodes))
            return
        for kind, node in nodes.items():
            print(node["name"] + " | " + kind + " | TCP " + str(node["port"]))
        return
    if options.command == "firewall-status":
        labels = {"active": "active / 已启用", "inactive": "inactive / 未启用", "unavailable": "unavailable / 未安装"}
        for backend, status in firewall_status().items():
            print(backend + ": " + labels[status])
        if shutil.which("firewall-cmd") and system_command(["firewall-cmd", "--state"], check=False).returncode == 0:
            print("Default zone / 默认区域: " + system_command(["firewall-cmd", "--get-default-zone"]).stdout.strip())
            print(system_command(["firewall-cmd", "--get-active-zones"]).stdout.strip())
        if shutil.which("ufw"):
            print(ufw_command(["status", "verbose"]).stdout.strip())
        return
    if options.command == "firewall-allow":
        numbers = options.ports
        if not numbers:
            root = checked_path(options.root)
            ensure_owned(root)
            numbers = [node["port"] for node in load_state(root)["nodes"].values()]
        print(firewall_allow(numbers, options.zone))
        return
    if options.command == "bbr-status":
        current = network_values()
        enabled = current["net.ipv4.tcp_congestion_control"] == "bbr"
        summary = "已开启 BBR 加速 / BBR acceleration enabled" if enabled else "未开启 BBR 加速 / BBR acceleration not enabled"
        color, reset = "", ""
        if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
            color, reset = ("\033[1;32m" if enabled else "\033[1;33m"), "\033[0m"
        print("\n" + color + "===== " + summary + " =====" + reset + "\n")
        print("当前拥塞控制 / Current algorithm: " + current["net.ipv4.tcp_congestion_control"])
        print("当前默认队列 / Default qdisc: " + current["net.core.default_qdisc"])
        print("可用算法 / Available algorithms: " + system_command(["sysctl", "-n", "net.ipv4.tcp_available_congestion_control"]).stdout.strip())
        print("本脚本管理 / Managed by this manager: " + ("是 / yes" if bbr_previous(BBR_PATH) is not None else "否 / no"))
        return
    if options.command in ("bbr-enable", "bbr-restore"):
        bbr_change(options.command == "bbr-enable")
        return
    if options.command == "selfcheck":
        print("SKYBYTE Xray Manager " + VERSION + " OK")
        return
    if options.command == "preflight":
        shared_port_check(checked_path(options.root), [int(options.port or 443)])
        installation_preflight(options)
        return
    if options.command == 'reality-input':
        domain(options.sni)
        host, number = options.target.rsplit(':', 1)
        domain(host)
        port(number)
        return
    if options.command == 'tls-input':
        certificate(options.cert, options.key, options.sni, options.ca_file)
        return
    if options.command == "download":
        download_binary(checked_path(options.file), options.asset, options.tag)
        return
    if options.command == "probe":
        host, number = options.target.rsplit(":", 1)
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.set_alpn_protocols(["h2"])
        with socket.create_connection((domain(host), port(number)), timeout=10) as connection:
            with context.wrap_socket(connection, server_hostname=domain(options.sni)) as secure:
                if secure.selected_alpn_protocol() != "h2":
                    raise ValueError("Target does not negotiate HTTP/2 / 握手目标不支持 HTTP/2")
                print(secure.version() + " / h2")
        return
    root, binary, unit = map(checked_path, (options.root, options.binary, options.unit))
    if options.command == "stage-ports":
        stage=checked_path(options.stage)
        if stage.parent!=root or not stage.name.startswith('.stage-'):raise ValueError('Invalid stage')
        state=load_state(stage)
        if any(k not in ('xhttp-reality','xhttp-tls') for k in state['nodes']):raise ValueError('Only XHTTP backups can be restored here / 此入口仅恢复 XHTTP 备份')
        for node in state['nodes'].values():print(node['port'])
        return
    if options.command in ('purge-plan', 'purge'):
        paths=purge_paths(root, binary, unit)
        if options.command=='purge':
            for path in paths:
                if path.exists():path.unlink()
        return
    if options.command == "guard":
        unit_guard(unit)
        ensure_owned(root, create=True)
    elif options.command == "prepare":
        if not options.kind:
            raise ValueError("Protocol required")
        print(prepare(root, binary, options))
    elif options.command == "warp-prepare":
        print(warp_prepare(root, binary, options.proxy_port, options.domains, options.disable))
    elif options.command == "ipv6-prepare":
        ensure_owned(root)
        state = ipv6_state(load_state(root), None if options.disable else options.address)
        stage = make_stage(root, state)
        try:
            finish_stage(stage, state, binary)
            print(stage)
        except BaseException:
            shutil.rmtree(stage)
            raise
    elif options.command == "commit":
        commit(root, Path(options.stage), binary, unit, options.active, options.enabled)
    elif options.command == "rollback":
        print(json_text(rollback(root, unit)))
    elif options.command == "journal":
        ensure_owned(root)
        print((root / ".transaction" / "meta.json").read_text())
    elif options.command == "finalize":
        finalize(root, Path(options.stage))
    elif options.command == "backup":
        backup(root, Path(options.file))
    elif options.command == "restore":
        print(restore_stage(root, binary, Path(options.file), options.ca_file))
    elif options.command == 'reality-targets':
        ensure_owned(root)
        for kind, node in load_state(root)['nodes'].items():
            if kind != 'xhttp-tls':
                print('\t'.join((kind, node['target'], node['sni'])))
    elif options.command == "show":
        ensure_owned(root)
        for kind, node in load_state(root)["nodes"].items():
            print(node["name"] + " | " + kind + " | TCP " + str(node["port"]))
            print(node_uri(kind, node))
            if 'ipv6_backup' in node:
                print(node_uri(kind, ipv6_node(node)))
    else:
        ensure_owned(root)
        state = copy.deepcopy(load_state(root))
        if options.kind not in state["nodes"]:
            raise ValueError("Protocol not installed / 协议未安装")
        if options.command == "remove":
            del state["nodes"][options.kind]
        elif options.command == "rename":
            state["nodes"][options.kind]["name"] = name(options.name)
        elif options.command == "edit":
            state = edit_state(state, options.kind, options.address, options.port, options.path)
        elif options.command == 'reality-edit':
            state = edit_reality(state, options.kind, options.sni, options.target)
            if options.check_only:
                return
        elif options.command == "refresh-tls":
            if options.kind != "xhttp-tls":
                raise ValueError("TLS protocol required")
            node = state["nodes"][options.kind]
            certificate(options.cert, options.key, node["sni"], options.ca_file)
        stage = make_stage(root, state)
        try:
            if options.command == "refresh-tls":
                write_private(stage / node["cert"], Path(options.cert).read_bytes())
                write_private(stage / node["key"], Path(options.key).read_bytes())
            finish_stage(stage, state, binary)
            print(stage)
        except BaseException:
            shutil.rmtree(stage)
            raise


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, ssl.SSLError, tarfile.TarError,
            zipfile.BadZipFile, TypeError, AttributeError) as error:
        print(error_message(error), file=sys.stderr)
        sys.exit(1)
