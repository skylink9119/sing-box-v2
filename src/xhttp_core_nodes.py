# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
def server_config(state, root):
    validate_state(state)
    inbounds = []
    for kind, node in state["nodes"].items():
        user = {"id": node["uuid"], "email": kind + "@skybyte.local"}
        stream = {"network": "raw" if kind == "vision" else "xhttp"}
        if kind == "vision":
            user["flow"] = "xtls-rprx-vision"
        else:
            stream["xhttpSettings"] = {"path": node["path"], "mode": "auto"}
        if kind == "xhttp-tls":
            stream.update(security="tls", tlsSettings={"minVersion": "1.2", "alpn": ["h2", "http/1.1"],
                "certificates": [{"certificateFile": str(root / node["cert"]), "keyFile": str(root / node["key"])}]})
        else:
            stream.update(security="reality", realitySettings={"show": False, "target": node["target"],
                "serverNames": [node["sni"]], "privateKey": node["private"], "shortIds": [node["short_id"]]})
        inbounds.append({"tag": kind, "listen": node["listen"], "port": node["port"], "protocol": "vless",
                         "settings": {"clients": [user], "decryption": "none"}, "streamSettings": stream})
    result = {"log": {"loglevel": "warning"}, "inbounds": inbounds,
            "outbounds": [{"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "block"}],
            "routing": {"domainStrategy": "IPOnDemand", "rules": [{"type": "field", "ip": ["127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12",
                "192.168.0.0/16", "169.254.0.0/16", "::1/128", "fc00::/7", "fe80::/10"], "outboundTag": "block"}]}}
    if "warp" in state:
        warp = state["warp"]
        result["outbounds"].append({"protocol": "socks", "tag": "warp", "settings": {
            "servers": [{"address": "127.0.0.1", "port": warp["port"]}]}})
        domains = ["domain:" + suffix for suffix in warp["domains"]]
        result["routing"]["rules"] += [
            {"type": "field", "network": "udp", "domain": domains, "outboundTag": "block"},
            {"type": "field", "network": "tcp", "domain": domains, "outboundTag": "warp"}]
        for inbound in inbounds:
            inbound["sniffing"] = {"enabled": True, "destOverride": ["http", "tls", "quic"], "routeOnly": True}
    return result


def warp_prepare(root, binary, number, domains, disable=False):
    ensure_owned(root)
    state = copy.deepcopy(load_state(root))
    if not state["nodes"] and not disable:
        raise ValueError("Install a node before configuring WARP / 请先安装节点，再设置 WARP 分流")
    if disable:
        state.pop("warp", None)
    else:
        state["warp"] = {"port": number, "domains": list(dict.fromkeys(domains))}
    validate_state(state)
    stage = make_stage(root, state)
    try:
        finish_stage(stage, state, binary)
        return stage
    except BaseException:
        shutil.rmtree(stage)
        raise


def warp_status(root, language="zh"):
    root = checked_path(root)
    warp = None
    if root.exists():
        ensure_owned(root)
        warp = load_state(root).get("warp")
    if not warp:
        return "Status: WARP routing disabled" if language == "en" else "当前状态：未启用 WARP 分流"
    if language == "en":
        return f"Routing: Selected domains use WARP\nLocal proxy: 127.0.0.1:{warp['port']} | Suffixes: {len(warp['domains'])}"
    return f"当前模式：仅指定域名使用 WARP\n本机代理：127.0.0.1:{warp['port']} | 域名后缀：{len(warp['domains'])} 个"


def warp_verify(number):
    number = port(number)
    if number < 1024:
        raise ValueError("WARP proxy port must be 1024–65535 / WARP 代理端口须为 1024–65535")
    listeners = system_command(["ss", "-H", "-ltn", f"( sport = :{number} )"]).stdout.splitlines()
    if not listeners or any(len(line.split()) < 4 or line.split()[3] not in (
            f"127.0.0.1:{number}", f"[::1]:{number}", f"::1:{number}") for line in listeners):
        raise ValueError("WARP proxy must listen only on loopback / WARP 代理须已启动且仅监听回环地址")
    result = system_command(["curl", "-q", "-fsSL", "--noproxy", "", "--proxy", f"socks5h://127.0.0.1:{number}",
        "--proto", "=https", "--proto-redir", "=https", "--connect-timeout", "4", "--max-time", "10", "--max-filesize", "65536",
        "https://www.cloudflare.com/cdn-cgi/trace"])
    trace = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    try:
        valid = trace.get("warp") in ("on", "plus") and ipaddress.ip_address(trace.get("ip", "")).is_global and re.fullmatch("[A-Z]{2}", trace.get("loc", ""))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("WARP egress could not be verified; routing unchanged / WARP 出口验证未通过，分流保持原样")
    return trace["ip"], trace["loc"]


def client_config(kind, node, socks_port=10808):
    stream = {"network": "raw" if kind == "vision" else "xhttp"}
    if kind.startswith("xhttp"):
        stream["xhttpSettings"] = {"path": node["path"], "mode": node["mode"], "host": node["sni"]}
    if kind == "xhttp-tls":
        stream.update(security="tls", tlsSettings={"serverName": node["sni"], "allowInsecure": False,
                                                     "alpn": ["h2", "http/1.1"], "fingerprint": "chrome"})
    else:
        stream.update(security="reality", realitySettings={"serverName": node["sni"], "fingerprint": "chrome",
            "publicKey": node["public"], "shortId": node["short_id"], "spiderX": "/"})
    user = {"id": node["uuid"], "encryption": "none"}
    if kind == "vision":
        user["flow"] = "xtls-rprx-vision"
    return {"log": {"loglevel": "warning"}, "inbounds": [{"listen": "127.0.0.1", "port": socks_port,
        "protocol": "socks", "settings": {"auth": "noauth", "udp": True}}], "outbounds": [{"tag": "proxy",
        "protocol": "vless", "settings": {"vnext": [{"address": node["address"], "port": node["port"],
        "users": [user]}]}, "streamSettings": stream}]}


def node_uri(kind, node):
    query = {"encryption": "none", "type": "tcp" if kind == "vision" else "xhttp",
             "security": "tls" if kind == "xhttp-tls" else "reality", "sni": node["sni"], "fp": "chrome"}
    if kind == "vision":
        query["flow"] = "xtls-rprx-vision"
    if kind == "xhttp-tls":
        query.update(allowInsecure="0", alpn="h2,http/1.1")
    else:
        query.update(pbk=node["public"], sid=node["short_id"], spx="/")
    if kind.startswith("xhttp"):
        query.update(path=node["path"], mode=node["mode"], host=node["sni"])
    host = node["address"]
    if ":" in host:
        host = "[" + host + "]"
    return f"vless://{node['uuid']}@{host}:{node['port']}?{urllib.parse.urlencode(query)}#{urllib.parse.quote(node['name'], safe='')}"


def engine_check(binary, config):
    result = subprocess.run([str(binary), "run", "-test", "-config", str(config)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    if result.returncode:
        raise ValueError("Xray rejected configuration / Xray 配置校验失败")


def load_state(root):
    p = root / "state.json"
    checked_path(p)
    return validate_state(json.loads(p.read_text())) if p.exists() else {"schema": 1, "nodes": {}}


def node_parameters(root, language="zh"):
    def tr(zh, en):
        return en if language == "en" else zh
    lines = [tr("========== 保密提醒 ==========", "========== KEEP PRIVATE =========="),
             tr("本脚本的节点配置、凭据、订阅和备份等重要数据保存在当前 VPS，请妥善保管。",
                "Node configuration, credentials, subscriptions and backups are stored on this VPS. Protect them."),
             tr("请在可信终端查看；不要公开节点参数、完整链接、二维码或截图。",
                "Use a trusted terminal. Do not publish node parameters, full links, QR codes or screenshots."),
             tr("请务必安装并启用防火墙：主菜单 d → 2；先放行 SSH 和实际节点端口。",
                "Install and enable a firewall: main menu d → 2. Allow SSH and actual node ports first.")]
    if not checked_path(root / "state.json").exists():
        return "\n".join(lines + [tr("尚未安装节点。", "No nodes installed.")])
    ensure_owned(root)
    state = load_state(root)
    for kind in KINDS:
        if kind not in state["nodes"]:
            continue
        node = state["nodes"][kind]
        lines += ["-" * 60, node["name"] + " | " + kind,
                  tr("连接地址: ", "Server address: ") + node["address"],
                  tr("端口: ", "Port: ") + str(node["port"]), "UUID: " + node["uuid"]]
        if kind == "xhttp-tls":
            na = tr("不适用（TLS 节点不使用 Reality）", "Not applicable (TLS node does not use Reality)")
            lines += [tr("公钥: ", "Public key: ") + na, "Short ID: " + na,
                      tr("TLS 域名（SNI）: ", "TLS SNI: ") + node["sni"],
                      tr("Reality 握手目标: ", "Reality target: ") + na]
        else:
            lines += [tr("公钥: ", "Public key: ") + node["public"], "Short ID: " + node["short_id"],
                      tr("握手网站（SNI）: ", "Handshake SNI: ") + node["sni"],
                      tr("Reality 握手目标: ", "Reality target: ") + node["target"]]
    if not state["nodes"]:
        lines.append(tr("尚未安装节点。", "No nodes installed."))
    return "\n".join(lines)


def ensure_owned(root, create=False):
    checked_path(root)
    marker = checked_path(root / ".owner")
    if root.exists():
        if not root.is_dir():
            raise ValueError("Managed path is not a directory")
        if marker.exists():
            if marker.read_text() != OWNER:
                raise ValueError("Unknown owner / 已有目录非本脚本管理")
        elif any(root.iterdir()) or not create:
            raise ValueError("Existing configuration refused / 拒绝覆盖现有配置")
    elif not create:
        raise ValueError("Not installed / 尚未安装")
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        if not marker.exists():
            write_private(marker, OWNER)
    state = load_state(root)
    for relative in owned_names(state) | {"language", ".transaction"}:
        checked_path(root / relative)


def tls_names(state):
    node = state["nodes"].get("xhttp-tls")
    return {node["cert"], node["key"]} if node else set()


def ipv6_node(node):
    result = copy.deepcopy(node)
    result['address'] = node['ipv6_backup']['address']
    result['name'] += '-IPv6备用'
    return result


def ipv6_state(state, value=None):
    result = copy.deepcopy(state)
    nodes = [n for n in result['nodes'].values() if not n.get('cdn')]
    if not nodes:
        raise ValueError('没有直连节点 / No direct nodes installed')
    for node in nodes:
        if value is None:
            backup = node.pop('ipv6_backup', None)
            if backup:
                node['listen'] = backup['previous_listen']
        else:
            if node['listen'] not in ('::', '0.0.0.0'):
                raise ValueError('回环节点保持不变，请先使用公网监听 / Loopback nodes are preserved; use a public listener first')
            previous = node.get('ipv6_backup', {}).get('previous_listen', node['listen'])
            node['ipv6_backup'] = {'address': str(ipaddress.IPv6Address(value)), 'previous_listen': previous}
            node['listen'] = '::'
    return validate_state(result)


def owned_names(state):
    return {"state.json", "config.json", "nodes.txt", "subscription-base64.txt"} | tls_names(state) | {
        "client-" + k + ".json" for k in state["nodes"]} | {
        "client-" + k + "-ipv6.json" for k, n in state["nodes"].items() if "ipv6_backup" in n}


def render_files(state, root):
    files = {"state.json": json_text(state), "config.json": json_text(server_config(state, root))}
    lines = [node_uri(k, n) for k, n in state["nodes"].items()]
    lines += [node_uri(k, ipv6_node(n)) for k, n in state['nodes'].items() if 'ipv6_backup' in n]
    nodes = "\n".join(lines) + ("\n" if lines else "")
    files["nodes.txt"] = nodes
    files["subscription-base64.txt"] = base64.b64encode(nodes.encode()).decode() + "\n"
    files.update({"client-" + k + ".json": json_text(client_config(k, n)) for k, n in state["nodes"].items()})
    files.update({'client-' + k + '-ipv6.json': json_text(client_config(k, ipv6_node(n)))
                  for k, n in state['nodes'].items() if 'ipv6_backup' in n})
    return files


def check_port(host, number):
    try:
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if ":" in host:
                listener.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            listener.bind((host, number))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            raise ValueError(f"TCP {number} is already in use; choose a free port. Existing services are preserved. / TCP {number} 已被占用，请选择空闲端口；不会停止已有服务。") from None
        raise


def installation_preflight(options):
    address(options.address)
    name(options.name)
    number = port(options.port)
    root = checked_path(options.root)
    # Inspect existing state without creating a directory or an ownership marker.
    # An empty directory is also a valid destination for a first installation.
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        ensure_owned(root)
        nodes = load_state(root)["nodes"]
        if options.kind in nodes:
            raise ValueError("Protocol already installed / 该协议已安装，请使用编辑节点功能；删除后重新安装会更换凭据")
        if number in {node["port"] for node in nodes.values()}:
            raise ValueError("TCP port already used by a managed node / 托管节点端口冲突，请选择其他空闲端口")
    check_port(options.listen, number)


def edit_state(state, kind, client_address=None, node_port=None, path=None):
    state = copy.deepcopy(state)
    if kind not in state["nodes"]:
        raise ValueError("Protocol not installed / 协议未安装")
    node = state["nodes"][kind]
    old_port = node["port"]
    if client_address is not None:
        node["address"] = address(client_address)
    if node_port is not None:
        node["port"] = port(node_port)
    if path is not None:
        if not kind.startswith("xhttp"):
            raise ValueError("XHTTP path requires an XHTTP node / 只有 XHTTP 节点可修改路径")
        node["path"] = xhttp_path(path)
    validate_state(state)
    # The running node owns its current port; probe only a changed port.
    if node["port"] != old_port:
        check_port(node["listen"], node["port"])
    return state


def edit_reality(state, kind, sni, target):
    state = copy.deepcopy(state)
    if kind not in ('vision', 'xhttp-reality') or kind not in state['nodes']:
        raise ValueError('Installed Reality node required / 请先选择已安装的 Reality 节点')
    host, number = target.rsplit(':', 1)
    node = state['nodes'][kind]
    node.update(sni=domain(sni), target=domain(host) + ':' + str(port(number)))
    return validate_state(state)
