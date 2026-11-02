# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
def download_binary(destination, asset, tag=CORE_VERSION):
    if not re.fullmatch(r"v[0-9]+(?:\.[0-9]+){2}", tag):
        raise ValueError("Invalid release version")
    allowed = {"Xray-linux-64.zip", "Xray-linux-arm64-v8a.zip", "Xray-macos-64.zip", "Xray-macos-arm64-v8a.zip"}
    if asset not in allowed:
        raise ValueError("Unsupported architecture")
    headers = {"User-Agent": "SKYBYTE-Xray-Manager"}
    if os.environ.get("SKYBYTE_GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["SKYBYTE_GITHUB_TOKEN"]
    request = urllib.request.Request("https://api.github.com/repos/XTLS/Xray-core/releases/tags/" + tag,
                                     headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)
    if metadata.get("draft") or metadata.get("prerelease") or metadata.get("tag_name") != tag:
        raise ValueError("Not a stable release")
    candidates = [a for a in metadata["assets"] if a["name"] == asset]
    if len(candidates) != 1:
        raise ValueError("Release asset missing")
    release_asset = candidates[0]
    expected = release_asset.get("digest", "")
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", expected):
        raise ValueError("Official SHA256 unavailable / 官方 SHA256 不可用")
    url = release_asset["browser_download_url"]
    if url != f"https://github.com/XTLS/Xray-core/releases/download/{tag}/{asset}":
        raise ValueError("Unexpected release URL")
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read(128 * 1024 * 1024 + 1)
    if len(data) > 128 * 1024 * 1024 or "sha256:" + hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Release digest mismatch / 核心下载校验失败")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = [i for i in archive.infolist() if i.filename == "xray"]
        if len(entries) != 1 or entries[0].file_size > 128 * 1024 * 1024:
            raise ValueError("Invalid binary archive")
        binary = archive.read(entries[0])
    write_private(destination, binary, 0o700)


def error_message(error):
    # External exceptions can contain credential-bearing URLs, paths or core output.
    if isinstance(error, ValueError):
        return str(error)
    if isinstance(error, urllib.error.HTTPError):
        return f"Download HTTP {error.code}; check GitHub access, rate limits and release availability / 下载返回 HTTP {error.code}，请检查 GitHub 访问、请求限额及版本是否存在"
    if isinstance(error, ssl.SSLError):
        return "TLS verification or handshake failed; check the target name, certificate and system time / TLS 验证或握手失败，请检查目标域名、证书和系统时间"
    if isinstance(error, (TimeoutError, urllib.error.URLError)):
        return "Network request failed; check DNS, outbound connectivity and retry / 网络请求失败，请检查 DNS、出站连接后重试"
    if isinstance(error, OSError):
        if error.errno in (errno.EACCES, errno.EPERM):
            return "Permission denied; use root and check directory permissions / 权限不足，请使用 root 并检查目录权限"
        if error.errno == errno.ENOENT:
            return "Required file or command missing; check file paths and dependencies / 所需文件或命令不存在，请检查文件路径与系统依赖"
        if error.errno == errno.ENOSPC:
            return "Insufficient disk space; free space before retrying / 磁盘空间不足，请清理空间后重试"
    if isinstance(error, subprocess.SubprocessError):
        return "Core or system command failed; check the binary and service status / 核心或系统命令失败，请检查核心文件及服务状态"
    return "Operation failed; check files, network and permissions / 操作失败，请检查文件、网络与权限"


def system_command(arguments, check=True):
    return subprocess.run(arguments, check=check, capture_output=True, text=True,
                          timeout=30, env={**os.environ, "LC_ALL": "C"})
