# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
def domain(value):
    value = value.strip().rstrip(".").lower()
    value = value.encode("idna").decode("ascii")
    if len(value) > 253 or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x)
                                    for x in value.split(".")):
        raise ValueError("Invalid domain / 域名无效")
    return value


def address(value):
    value = value.strip()
    if not value:
        raise ValueError("Client address required: enter your VPS public IP or domain / 客户端连接地址必填：请输入本 VPS 的公网 IP 或域名")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return domain(value)


def port(value):
    if isinstance(value, bool) or not str(value).isdigit() or not 1 <= int(value) <= 65535:
        raise ValueError("Invalid port / 端口必须为 1–65535")
    return int(value)


def name(value):
    if not value or len(value) > 64 or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Invalid node name / 节点名须为 1–64 个字符")
    return value


def xhttp_path(value):
    if not re.fullmatch(r"/[A-Za-z0-9/_~-]{1,127}", value):
        raise ValueError("Invalid XHTTP path / XHTTP 路径必须以 / 开头")
    return value


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ValueError("Invalid REALITY key / REALITY 密钥无效")
    if len(base64.urlsafe_b64decode(value + "=")) != 32:
        raise ValueError("Invalid REALITY key")
    return value


def certificate(cert, private_key, host, ca_file=None):
    cert, private_key = checked_path(cert), checked_path(private_key)
    if not cert.is_file() or not private_key.is_file():
        raise ValueError("Certificate files missing / 证书文件不存在")
    if cert.stat().st_size > 1024 * 1024 or private_key.stat().st_size > 1024 * 1024:
        raise ValueError("Certificate file too large")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    def reject_password():
        raise ValueError("Encrypted private keys are not supported for unattended service startup / 自动启动服务不支持加密私钥，请提供未加密的服务端私钥并妥善保密")
    # Server operation is unattended. Reject encrypted keys without OpenSSL
    # prompting on the administrator's terminal and stalling the menu.
    context.load_cert_chain(str(cert), str(private_key), password=reject_password)
    decoded = ssl._ssl._test_decode_cert(str(cert))
    if ssl.cert_time_to_seconds(decoded["notAfter"]) <= __import__("time").time() + 86400:
        raise ValueError("Certificate expired or expires within 24h / 证书已过期或即将过期")
    host = domain(host)
    def matches(pattern):
        pattern = pattern.lower()
        return pattern == host or (pattern.startswith("*.") and
                                  host.endswith(pattern[1:]) and
                                  len(host.split(".")) == len(pattern.split(".")))
    if not any(matches(v) for k, v in decoded.get("subjectAltName", []) if k == "DNS"):
        raise ValueError("Certificate domain mismatch / 证书域名不匹配")
    command = ["openssl", "verify", "-purpose", "sslserver", "-untrusted", str(cert)]
    if ca_file:
        command += ["-CAfile", str(checked_path(ca_file))]
    command += [str(cert)]
    if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode:
        raise ValueError("Certificate chain untrusted / 证书链不受系统信任")


def new_keys(binary):
    result = subprocess.run([str(binary), "x25519"], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError("Xray key generation failed / Xray 密钥生成失败")
    fields = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            label, value = line.split(":", 1)
            fields[re.sub(r"[^a-z]", "", label.lower())] = value.strip()
    private = fields.get("privatekey")
    public = fields.get("password") or fields.get("passwordpublickey") or fields.get("publickey")
    return key(private), key(public)


def validate_state(state):
    if not isinstance(state, dict) or set(state) not in ({"schema", "nodes"}, {"schema", "nodes", "warp"}) or state["schema"] != 1:
        raise ValueError("Unknown state format / 非托管状态格式")
    if "warp" in state:
        warp = state["warp"]
        if not isinstance(warp, dict) or set(warp) != {"port", "domains"} or type(warp["port"]) is not int or not 1024 <= warp["port"] <= 65535:
            raise ValueError("Invalid WARP proxy / WARP 代理配置无效")
        domains = warp["domains"]
        if not isinstance(domains, list) or not 1 <= len(domains) <= 128 or any(not isinstance(d, str) or domain(d) != d or "." not in d for d in domains) or len(set(domains)) != len(domains):
            raise ValueError("Invalid WARP domain suffixes / WARP 域名后缀无效")
    if not isinstance(state["nodes"], dict) or not set(state["nodes"]) <= set(KINDS):
        raise ValueError("Invalid protocol state")
    ports = set()
    for kind, node in state["nodes"].items():
        required = {"name", "uuid", "port", "address", "listen", "sni"}
        extra = {"private", "public", "short_id", "target"} if kind != "xhttp-tls" else {"cert", "key", "cdn"}
        if kind.startswith("xhttp"):
            extra |= {"path", "mode"}
        if not isinstance(node, dict) or set(node) not in (required | extra, required | extra | {"ipv6_backup"}):
            raise ValueError("Invalid node fields")
        if "ipv6_backup" in node:
            backup = node["ipv6_backup"]
            if not isinstance(backup, dict) or set(backup) != {"address", "previous_listen"}:
                raise ValueError("Invalid IPv6 backup metadata")
            ip = ipaddress.IPv6Address(backup["address"])
            if not ip.is_global or ip.is_multicast or ip.ipv4_mapped or ip.is_reserved or "%" in backup["address"] or node["listen"] != "::" or backup["previous_listen"] not in ("::", "0.0.0.0") or node.get("cdn"):
                raise ValueError("Invalid IPv6 backup address/listener")
        name(node["name"])
        if str(uuid.UUID(node["uuid"])) != node["uuid"]:
            raise ValueError("Invalid UUID")
        p = port(node["port"])
        if p in ports:
            raise ValueError("Duplicate TCP port / TCP 端口冲突")
        ports.add(p)
        if "warp" in state and p == state["warp"]["port"]:
            raise ValueError("WARP proxy conflicts with a node port / WARP 代理与节点端口冲突")
        address(node["address"])
        domain(node["sni"])
        if node["listen"] not in ("0.0.0.0", "::", "127.0.0.1", "::1"):
            raise ValueError("Invalid listen address")
        if kind != "xhttp-tls":
            key(node["private"])
            key(node["public"])
            if not re.fullmatch(r"[0-9a-f]{16}", node["short_id"]):
                raise ValueError("Invalid short ID")
            target_host, target_port = node["target"].rsplit(":", 1)
            domain(target_host)
            port(target_port)
        else:
            if not isinstance(node["cdn"], bool):
                raise ValueError("Invalid CDN setting")
            for field, suffix in (("cert", "crt"), ("key", "key")):
                if node[field] != f"tls/{node['uuid']}.{suffix}":
                    raise ValueError("Invalid certificate path")
        if kind.startswith("xhttp"):
            xhttp_path(node["path"])
            if node["mode"] not in MODES:
                raise ValueError("Invalid XHTTP mode")
        if kind == "xhttp-tls" and node["cdn"] and node["mode"] == "stream-one":
            raise ValueError("Use packet-up or stream-up for CDN / CDN 请使用 packet-up 或 stream-up")
    return state
