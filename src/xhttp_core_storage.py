# Reused from SKYBYTE Xray Manager v0.1.34; see docs/XHTTP.md.
def checked_path(value):
    p = Path(value)
    if not p.is_absolute() or any(c in str(p) for c in '\n\r\x00%'):
        raise ValueError("Unsafe path / 路径无效")
    for component in (p, *p.parents):
        if component.is_symlink():
            raise ValueError("Symlink refused / 拒绝符号链接")
    return p


def write_private(path, data, mode=0o600):
    path = checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data if isinstance(data, bytes) else data.encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
