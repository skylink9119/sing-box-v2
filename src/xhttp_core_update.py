# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
MANAGER_REPO = "skylink9119/skybyte-xray-manager"
MANAGER_HEADER = b"#!/usr/bin/env bash\n# SKYBYTE Xray Manager standalone;"
MAX_MANAGER = 2 * 1024 * 1024


def manager_version(tag):
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Invalid manager version / 管理脚本版本无效")
    return tuple(map(int, tag[1:].split(".")))


def manager_release(tag=None):
    if tag is not None:
        manager_version(tag)
    endpoint = "latest" if tag is None else "tags/" + tag
    request = urllib.request.Request("https://api.github.com/repos/" + MANAGER_REPO + "/releases/" + endpoint,
                                     headers={"User-Agent": "SKYBYTE-Xray-Manager", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read(MAX_MANAGER + 1)
    if len(data) > MAX_MANAGER:
        raise ValueError("Release metadata too large / 发布信息过大")
    metadata = json.loads(data)
    actual = metadata.get("tag_name")
    manager_version(actual)
    if metadata.get("draft") or metadata.get("prerelease") or (tag is not None and actual != tag):
        raise ValueError("Not the requested stable manager release / 不是指定的正式管理脚本发布")
    return metadata


def manager_asset(metadata, filename):
    assets = [asset for asset in metadata["assets"] if asset.get("name") == filename]
    if len(assets) != 1:
        raise ValueError("Manager release asset missing or duplicated / 管理脚本发布附件缺失或重复")
    asset = assets[0]
    expected_url = "https://github.com/" + MANAGER_REPO + "/releases/download/" + metadata["tag_name"] + "/" + filename
    if asset.get("browser_download_url") != expected_url:
        raise ValueError("Unexpected manager download URL / 管理脚本下载地址异常")
    digest = asset.get("digest", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Manager release SHA256 unavailable / 管理脚本官方 SHA256 不可用")
    with urllib.request.urlopen(expected_url, timeout=120) as response:
        payload = response.read(MAX_MANAGER + 1)
    if len(payload) > MAX_MANAGER or "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("Manager release SHA256 mismatch / 管理脚本发布 SHA256 校验失败")
    return payload


def manager_target(target):
    target = checked_path(target)
    if target.name != "manager.sh":
        raise ValueError("Update the installed manager.sh only / 仅支持更新已安装的 manager.sh")
    marker = checked_path(target.parent / ".owner")
    if not marker.is_file() or marker.read_text() != OWNER:
        raise ValueError("Manager is not installed here; use install.sh first / 此目录不是已安装的管理器，请先运行 install.sh")
    backup = checked_path(target.parent / "manager.previous.sh")
    for path in (target, backup):
        if path.exists() and (not path.is_file() or not path.read_bytes().startswith(MANAGER_HEADER)):
            raise ValueError("Existing manager/backup is not owned / 已有脚本或备份不属于本管理器")
    if not target.is_file():
        raise ValueError("Installed manager missing / 已安装的管理脚本缺失")
    return target, backup


def check_manager(path, tag):
    system_command(["bash", "-n", str(path)])
    version = system_command(["bash", str(path), "--version"]).stdout.strip()
    selfcheck = system_command(["bash", str(path), "--self-check"]).stdout.strip()
    if version != "SKYBYTE Xray Manager " + tag[1:] or selfcheck != version + " OK":
        raise ValueError("Manager version/self-check mismatch / 管理脚本版本或自检不符")


def manager_update(target, tag):
    if manager_version(tag) <= manager_version("v" + VERSION):
        raise ValueError("Manager downgrade/reinstall refused / 不更新到相同或更旧的管理脚本版本")
    target, backup = manager_target(target)
    old = target.read_bytes()
    installed = re.findall(rb"^VERSION=([0-9]+\.[0-9]+\.[0-9]+)$", old, re.MULTILINE)
    if len(installed) != 1 or manager_version(tag) <= manager_version("v" + installed[0].decode("ascii")):
        raise ValueError("Installed manager is newer or its version is unknown / 已安装脚本版本较新或无法识别，不覆盖")
    metadata = manager_release(tag)
    manifest = manager_asset(metadata, "SHA256SUMS").decode("utf-8")
    checksums = []
    for line in manifest.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[1] == "xray-manager.sh":
            checksums.append(fields[0])
    if len(checksums) != 1 or not re.fullmatch(r"[a-f0-9]{64}", checksums[0]):
        raise ValueError("Invalid manager checksum manifest / 管理脚本校验清单无效")
    payload = manager_asset(metadata, "xray-manager.sh")
    if hashlib.sha256(payload).hexdigest() != checksums[0] or not payload.startswith(MANAGER_HEADER):
        raise ValueError("Manager payload mismatch / 管理脚本内容校验失败")
    descriptor, filename = tempfile.mkstemp(prefix=".manager-update-", dir=target.parent)
    os.close(descriptor)
    candidate = Path(filename)
    try:
        write_private(candidate, payload, 0o700)
        # Only the verified release payload is executed for its built-in diagnostics.
        check_manager(candidate, tag)
        write_private(backup, old, 0o700)
        write_private(target, payload, 0o700)
        try:
            check_manager(target, tag)
        except BaseException as error:
            try:
                write_private(target, old, 0o700)
            except OSError:
                raise ValueError("Manager rollback incomplete; restore manager.previous.sh / 脚本回退未完成，请从 manager.previous.sh 恢复") from error
            raise
    finally:
        candidate.unlink(missing_ok=True)
