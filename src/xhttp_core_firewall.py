# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
def ufw_command(arguments, check=True):
    try:
        return system_command(["ufw", *arguments], check=check)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or "") + (error.stdout or "")
        reason = "check UFW diagnostics / 请检查 UFW 诊断输出"
        for token, label in [("Invalid position", "empty-rule position is invalid / 空规则列表位置无效"),
                             ("Permission denied", "permission/kernel capability denied / 权限或内核能力不足"),
                             ("Could not load logging rules", "logging rules could not load / 日志规则加载失败"),
                             ("iptables", "iptables backend failed / iptables 后端失败")]:
            if token in detail:
                reason = label
                break
        command = "ufw " + " ".join(arguments)
        raise ValueError("UFW step failed: " + command + " (exit " + str(error.returncode) + "); " + reason +
                         " / UFW 操作失败，具体命令如上；未显示外部异常中的敏感内容") from None
    except subprocess.TimeoutExpired:
        raise ValueError("UFW command timed out / UFW 命令超时: ufw " + " ".join(arguments)) from None
    except FileNotFoundError:
        raise ValueError("UFW executable missing; check package/PATH / 找不到 UFW 可执行文件，请检查安装与 PATH") from None


def ufw_state():
    if not shutil.which("ufw"):
        return "absent"
    result = ufw_command(["status"])
    if result.stdout.startswith("Status: active"):
        return "active"
    if result.stdout.startswith("Status: inactive"):
        return "inactive"
    raise ValueError("Cannot determine UFW status / 无法识别 UFW 状态")


def ufw_disable():
    if ufw_state() == "absent":
        return "absent"
    ufw_command(["--force", "disable"])
    if ufw_state() != "inactive":
        raise ValueError("UFW disable not verified; package removal stopped / 未确认 UFW 已停用，停止卸载软件包")
    return "disabled"


def ufw_package_state():
    result = system_command(["dpkg-query", "-W", "-f=${Status}", "ufw"], check=False)
    if result.returncode == 1:
        return "absent"
    if result.returncode != 0:
        raise ValueError("Cannot read UFW package status / 无法读取 UFW 软件包状态")
    status = result.stdout.strip()
    if status == "install ok installed":
        return "installed"
    fields = status.split()
    if (len(fields) == 3 and fields[0] in ("install", "deinstall", "purge", "unknown")
            and fields[1] == "ok" and fields[2] in ("not-installed", "config-files")):
        return "config-files" if fields[2] == "config-files" else "absent"
    raise ValueError("UFW package is held or incomplete; fix package state first / UFW 软件包被保留或状态不完整，请先修复软件包状态")


def ufw_remove_plan(purge=False):
    state = ufw_package_state()
    if state == "absent" or (state == "config-files" and not purge):
        return "absent"
    if state == "installed" and not shutil.which("ufw"):
        raise ValueError("UFW package files are missing; repair it before removal / UFW 软件包文件缺失，请先修复后再停用和卸载")
    try:
        # --no-act MUST precede the action; never remove files during preflight.
        system_command(["dpkg", "--no-act", "--purge" if purge else "--remove", "ufw"])
    except (OSError, subprocess.SubprocessError):
        raise ValueError("UFW removal dependency/lock check failed; no firewall changes / UFW 卸载依赖或锁检查失败，未改变防火墙；请检查依赖 UFW 的软件及软件包锁") from None
    return "config-files" if state == "config-files" else "ready"


def firewall_status():
    status = {"ufw": "unavailable", "firewalld": "unavailable"}
    ufw = ufw_state()
    if ufw != "absent":
        status["ufw"] = ufw
    if shutil.which("firewall-cmd"):
        result = system_command(["firewall-cmd", "--state"], check=False)
        if result.returncode == 0 and result.stdout.strip() == "running":
            status["firewalld"] = "active"
        elif result.returncode == 252:
            status["firewalld"] = "inactive"
        else:
            raise ValueError("Cannot determine firewalld status / 无法识别 firewalld 状态")
    return status


def firewall_allow(numbers, zone=""):
    numbers = sorted({port(number) for number in numbers})
    if not numbers:
        raise ValueError("No TCP ports selected / 没有可放行的 TCP 端口")
    if zone and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", zone):
        raise ValueError("Invalid firewalld zone / firewalld 区域名称无效")
    status = firewall_status()
    active = [key for key, value in status.items() if value == "active"]
    if len(active) != 1:
        raise ValueError("Exactly one active UFW/firewalld is required; configure your firewall first / 需要仅有一个已启用的 UFW/firewalld，请先配置防火墙；未修改规则")
    if active[0] == "ufw":
        for number in numbers:
            ufw_command(["allow", "in", "proto", "tcp", "to", "any", "port", str(number)])
        return "UFW"
    if not zone:
        zone = system_command(["firewall-cmd", "--get-default-zone"]).stdout.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", zone):
        raise ValueError("Invalid firewalld zone / firewalld 区域名称无效")
    zones = system_command(["firewall-cmd", "--get-zones"]).stdout.split()
    if zone not in zones:
        raise ValueError("Unknown firewalld zone / firewalld 区域不存在")
    # No reload: change just these ports in the chosen runtime and permanent zone.
    for number in numbers:
        for permanent in (True, False):
            args = ["firewall-cmd", "--zone=" + zone] + (["--permanent"] if permanent else [])
            query = system_command(args + [f"--query-port={number}/tcp"], check=False)
            if query.returncode not in (0, 1):
                raise ValueError("firewalld query failed / firewalld 规则查询失败")
            if query.returncode == 1:
                system_command(args + [f"--add-port={number}/tcp"])
                if system_command(args + [f"--query-port={number}/tcp"], check=False).returncode != 0:
                    raise ValueError("firewalld verification failed / firewalld 放行验证失败")
    return "firewalld / " + zone


def netfilter_label(value):
    # Kernel object names can contain control characters; never emit them verbatim.
    return re.sub(r"[^A-Za-z0-9_.:-]", "?", str(value))[:64]


def nft_objects(text):
    try:
        data = json.loads(text)
    except ValueError:
        raise ValueError("Cannot parse nft JSON; UFW setup stopped / 无法解析 nft JSON，已停止 UFW 初始化") from None
    if not isinstance(data, dict) or not isinstance(data.get("nftables"), list):
        raise ValueError("Unknown nft JSON structure / 无法识别 nft JSON 结构")
    for item in data["nftables"]:
        if not isinstance(item, dict) or len(item) != 1:
            raise ValueError("Unknown nft object / 无法识别 nft 对象")
        kind, value = next(iter(item.items()))
        if not isinstance(value, dict):
            raise ValueError("Unknown nft object fields / 无法识别 nft 对象字段")
    return data["nftables"]


def nft_fail2ban_objects(items):
    """Recognize an isolated, early input chain containing only TCP address bans."""
    members = [item for item in items if any(value.get("family") == "inet" and
               value.get("name" if kind == "table" else "table") == "f2b-table"
               for kind, value in item.items())]
    if not members:
        return []
    tables = [item["table"] for item in members if "table" in item]
    chains = [item["chain"] for item in members if "chain" in item]
    set_values = [item["set"] for item in members if "set" in item]
    if any(not isinstance(value.get("name"), str) for value in set_values):
        return []
    sets = {value["name"]: value for value in set_values}
    rules = [item["rule"] for item in members if "rule" in item]
    if (len(tables) != 1 or len(chains) != 1 or not sets or not rules or
            len(members) != 2 + len(sets) + len(rules)):
        return []
    if set(tables[0]) - {"family", "name", "handle", "comment"}:
        return []
    chain = chains[0]
    if (set(chain) - {"family", "table", "name", "handle", "type", "hook", "prio", "policy", "comment"} or
            type(chain.get("prio")) is not int or
            (chain.get("name"), chain.get("type"), chain.get("hook"), chain.get("prio"), chain.get("policy")) !=
            ("f2b-chain", "filter", "input", -1, "accept")):
        return []
    for name, value in sets.items():
        if (not isinstance(name, str) or not re.fullmatch(r"addr6?-set-[A-Za-z0-9_.-]+", name) or
                value.get("type") != ("ipv6_addr" if name.startswith("addr6-") else "ipv4_addr") or
                set(value) - {"family", "table", "name", "handle", "type", "flags", "elem", "comment",
                              "size", "timeout", "gc-interval"} or
                not isinstance(value.get("flags", []), list) or
                any(flag not in ("interval", "timeout") for flag in value.get("flags", [])) or
                not isinstance(value.get("elem", []), list)):
            return []
    referenced = set()
    for rule in rules:
        if (rule.get("chain") != "f2b-chain" or
                set(rule) - {"family", "table", "chain", "handle", "expr", "comment"}):
            return []
        expressions = rule.get("expr")
        if not isinstance(expressions, list) or len(expressions) not in (3, 4):
            return []
        verdict = expressions[-1]
        if verdict != {"drop": None}:
            if (not isinstance(verdict, dict) or set(verdict) != {"reject"} or
                    verdict["reject"] not in [{"type": family, "expr": "port-unreachable"}
                                               for family in ("icmp", "icmpv6", "icmpx")]):
                return []
        matches = []
        for expression in expressions[:-1]:
            if not isinstance(expression, dict) or len(expression) != 1:
                return []
            if "counter" in expression:
                if (not isinstance(expression["counter"], dict) or
                        set(expression["counter"]) - {"packets", "bytes"}):
                    return []
            elif "match" in expression:
                matches.append(expression["match"])
            else:
                return []
        if len(matches) != 2 or any(not isinstance(match, dict) or
                set(match) != {"op", "left", "right"} or match["op"] != "==" for match in matches):
            return []
        port_matches = [match for match in matches if match["left"] == {"payload": {"protocol": "tcp", "field": "dport"}}]
        if len(port_matches) != 1:
            return []
        ports = port_matches[0]["right"]
        ports = ports.get("set") if isinstance(ports, dict) and set(ports) == {"set"} else [ports]
        if not isinstance(ports, list) or not ports or any(type(number) is not int or not 1 <= number <= 65535 for number in ports):
            return []
        source = next(match for match in matches if match is not port_matches[0])
        reference = source["right"]
        if not isinstance(reference, str) or not reference.startswith("@") or reference[1:] not in sets:
            return []
        address_set = sets[reference[1:]]
        protocol = "ip6" if address_set["type"] == "ipv6_addr" else "ip"
        if source["left"] != {"payload": {"protocol": protocol, "field": "saddr"}}:
            return []
        referenced.add(reference[1:])
    return members if referenced == set(sets) else []


def nft_fail2ban_signature(items):
    # Ban elements and counters change independently under the Fail2ban daemon.
    result = set()
    for item in nft_fail2ban_objects(items):
        kind, value = next(iter(item.items()))
        value = {key: data for key, data in value.items() if key not in ("handle", "elem")}
        if kind == "rule":
            value["expr"] = [expression for expression in value["expr"] if "counter" not in expression]
        result.add(json.dumps({kind: value}, sort_keys=True))
    return result


def nft_inspect(text):
    items = nft_objects(text)
    preserved = nft_fail2ban_objects(items)
    signature = nft_fail2ban_signature(preserved)
    for item in items:
        kind, value = next(iter(item.items()))
        if kind == "metainfo" or item in preserved:
            continue
        location = "/".join(netfilter_label(value.get(field, "?")) for field in ("family", "table", "chain" if kind == "rule" else "name"))
        if kind == "table":
            if not all(isinstance(value.get(field), str) for field in ("family", "name")):
                raise ValueError("Invalid nft table / nft 表信息异常")
            continue
        if kind == "chain":
            if not all(isinstance(value.get(field), str) for field in ("family", "table", "name")):
                raise ValueError("Invalid nft chain / nft 链信息异常")
            if "hook" in value or "policy" in value:
                if value.get("policy") != "accept":
                    return "chain " + location + " policy=" + netfilter_label(value.get("policy", "unknown")), signature
            continue
        # Rules (including ACCEPT/NAT), sets, flowtables and unknown state remain guarded.
        return netfilter_label(kind) + " " + location, signature
    return None, signature


def nft_conflict(text):
    return nft_inspect(text)[0]


def verify_fail2ban_preserved(signature):
    if not signature:
        return
    try:
        current = nft_fail2ban_signature(nft_objects(system_command(["nft", "-j", "list", "ruleset"]).stdout))
        if signature <= current:
            return
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    raise ValueError("Fail2ban preservation not verified; inspect its status before retrying / 未确认原有 Fail2ban 封禁结构保留，请先检查其状态后重试")


def iptables_conflict(text):
    table = "?"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line == "COMMIT":
            continue
        if line.startswith("*"):
            table = netfilter_label(line[1:])
            continue
        fields = line.split()
        if line.startswith(":") and len(fields) == 3 and fields[1] in ("ACCEPT", "-") and re.fullmatch(r"\[[0-9]+:[0-9]+\]", fields[2]):
            # With no rules anywhere, an unreferenced empty user chain has no effect.
            continue
        if line.startswith(":"):
            return table + "/" + netfilter_label(fields[0][1:]) + " policy=" + netfilter_label(fields[1] if len(fields) > 1 else "unknown")
        if line.startswith("-A ") and len(fields) >= 2:
            return "rule " + table + "/" + netfilter_label(fields[1])
        return "unrecognized entry / 无法识别条目 " + table
    return None


def firewall_setup_check():
    status = firewall_status()
    if status["firewalld"] == "active" or status["ufw"] == "active":
        raise ValueError("A firewall is already active; use the port allow menu / 已有防火墙启用，请使用端口放行菜单，不重复初始化")
    preserved = set()
    # Preserve a validated independent Fail2ban input chain; guard all other rules.
    for command in ("nft", "iptables-save", "ip6tables-save", "iptables-legacy-save", "ip6tables-legacy-save"):
        if not shutil.which(command):
            continue
        args = [command, "-j", "list", "ruleset"] if command == "nft" else [command]
        try:
            rules = system_command(args).stdout
        except (OSError, subprocess.SubprocessError):
            raise ValueError("Cannot inspect " + command + "; UFW setup stopped / 无法检查 " + command + "，已停止 UFW 初始化，请检查权限与内核支持") from None
        if command == "nft":
            conflict, preserved = nft_inspect(rules)
        else:
            conflict = iptables_conflict(rules)
        if conflict:
            raise ValueError("Existing netfilter state: " + command + " / " + conflict +
                             "; inspect it before enabling UFW / 检测到已有规则或策略，来源如上；请先核对，不自动清空或覆盖")
    return preserved


def firewall_setup_plan(root, ssh_ports, extra_ports):
    ssh = {port(number) for number in ssh_ports}
    if not ssh:
        raise ValueError("Confirm at least one SSH TCP port / 必须确认至少一个 SSH TCP 端口")
    connection = os.environ.get("SSH_CONNECTION", "")
    if connection:
        fields = connection.split()
        if len(fields) != 4:
            raise ValueError("Cannot identify current SSH port / 无法识别当前 SSH 连接端口")
        ipaddress.ip_address(fields[0]); ipaddress.ip_address(fields[2])
        ssh.add(port(fields[3]))
    nodes = set()
    root = checked_path(root)
    if root.exists():
        ensure_owned(root)
        nodes = {node["port"] for node in load_state(root)["nodes"].values()}
    return sorted(ssh), sorted((nodes | {port(number) for number in extra_ports}) - ssh)


def firewall_setup(root, ssh_ports, extra_ports, config=Path("/etc/default/ufw")):
    ssh, others = firewall_setup_plan(root, ssh_ports, extra_ports)
    preserved = firewall_setup_check()
    if not shutil.which("ufw"):
        raise ValueError("Install UFW first / 请先安装 UFW")
    text = checked_path(config).read_text()
    values = re.findall(r'^\s*IPV6=["\']?(yes|no)["\']?\s*$', text, re.MULTILINE)
    if values != ["yes"]:
        raise ValueError("UFW requires IPV6=yes; inspect /etc/default/ufw / 请先核对 /etc/default/ufw 并设置 IPV6=yes，避免遗漏 IPv6 防护")
    added = ufw_command(["show", "added"]).stdout
    if re.search(r'^ufw\s+(?:deny|reject|limit|route|insert|prepend)\b', added, re.MULTILINE):
        raise ValueError("Existing restrictive UFW rules require manual review / 已有拒绝、限速或路由 UFW 规则，请手动核对后启用")
    # Stage SSH allows first while inactive; never assume SSH uses port 22.
    for number in ssh + others:
        ufw_command(["prepend", "allow", "in", "proto", "tcp", "to", "any", "port", str(number)])
    ufw_command(["default", "deny", "incoming"])
    ufw_command(["default", "allow", "outgoing"])
    try:
        ufw_command(["--force", "enable"])
        if firewall_status()["ufw"] != "active":
            raise ValueError("UFW did not become active / UFW 未成功启用")
        verify_fail2ban_preserved(preserved)
    except BaseException as error:
        try:
            ufw_command(["--force", "disable"])
            if firewall_status()["ufw"] != "inactive":
                raise ValueError("UFW still active")
            verify_fail2ban_preserved(preserved)
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ValueError("UFW enable/rollback incomplete; check UFW and Fail2ban from provider console / UFW 启用或回退未完成，请通过服务商控制台检查 UFW 与 Fail2ban 状态；配置文件保留") from error
        raise
    return bool(preserved)
