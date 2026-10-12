# Audit and testing / 审计与测试

## Reviewed baseline / 检查范围

All four baseline files were read: `singbox-v2.sh`, `install.sh`, `README.md`, `README_EN.md`. The user's Desktop copies were compared byte-for-byte and match the original GitHub revision.

## Problems and fixes / 问题与修复

| Original problem | Change |
| --- | --- |
| Function `install()` shadowed the system executable; enabling auto-update called the protocol installer | Renamed to `install_protocol`; system file installation explicitly uses `command install` |
| Backup config directory and binary shared the same pathname | Separate `config/` and `sing-box.bin`; snapshot external TLS files; restore with rollback |
| Binary copy could copy onto itself | Install official release directly into the managed binary path |
| Update executed a package installer that could alter config/service | Download only a checksum-verified binary; validate candidate before replacing; shared manual/automatic update path |
| Self-signed exports only had placeholders; links failed certificate trust | Embed public cert in sing-box JSON and Mihomo trust settings; export PEM and fingerprint; preserve certificate verification |
| Existing TLS files were accepted without validation | Check expiry, hostname/IP, and public/private key matching |
| HY2 URI did not encode arbitrary credentials | Percent-encode authentication before creating the URI |
| Protocol selection trusted stale metadata | Detect active protocol types from actual server inbounds |
| SSH port detection relied on manual entry | Detect listener/config/current connection ports and require verification; preserve detected SSH rules |
| Enabling UFW omitted existing hopping ranges | Include active UDP range and provide explicit UDP firewall audits |
| Leading-zero/oversized ports could break arithmetic | Bound input length and use base-10 conversion |
| Actions could end the whole menu on failure/cancellation | Isolate actions under strict mode and return to the menu; keep error output visible |
| Installing chrony could replace active timesyncd | Avoid installing chrony when an existing time-sync service is active |
| README menu numbers and feature claims contradicted each other | Rewritten bilingual docs matching implemented behavior |
| No automated regression suite | Add unittest suite and Ubuntu/Debian CI |

## Automated tests / 自动化测试

The regression suite invokes actual Bash functions with isolated filesystem paths. Only OS-mutating commands (apt, systemctl, UFW, nftables, sysctl) are mocked; real crypto, configuration export, backup filesystem operations and protocol engine processes run where applicable.

- YES case variants, port boundaries, language persistence and both branded menus.
- Three actual server configurations and protocol detection with stale cached mode.
- Base64/URI encoding, private file permissions, self-signed cert embedding and fingerprint.
- Certificate hostname/IP mismatch and mismatched private key rejection.
- External TLS backup/restore and update rejection/rollback.
- SSH detection, UFW allow rules, UDP audit and hopping systemd persistence.
- Initialization, BBR/FQ, daily/monthly vnStat and service restart config checks.
- Weekly update manager executable and timer generation.
- Matching release digest accepted; corrupted digest rejected without replacing target.
- Real sing-box client → HY2 server → local HTTP forwarding; removing certificate trust fails.
- Real Mihomo YAML validation and Mihomo client → sing-box HY2 server → local HTTP forwarding.

Local development result: 58 tests passed, including real HY2 forwarding with both clients and rejection without certificate trust; `bash -n`, ShellCheck and `git diff --check` passed.

Local development validation: macOS arm64, Bash 3.2, ShellCheck 0.11.0, OpenSSL 3.6.2, sing-box 1.14.3, Mihomo 1.19.32. CI pins the same protocol engine releases on Ubuntu 24.04 / Debian 12 with the distributions' Bash/OpenSSL/ShellCheck.

```bash
for file in install.sh singbox-v2.sh src/*.sh; do bash -n "$file"; done
shellcheck install.sh singbox-v2.sh
SING_BOX_BIN=/path/to/sing-box MIHOMO_BIN=/path/to/mihomo python3 -m unittest discover -s tests -v
```

Without engine paths, engine-specific tests are skipped. PyYAML is required for Mihomo tests. All credentials, keys, certificates and generated exports stay in temporary directories.

## Remaining live validation / 真实 VPS 验收

No production VPS was provided. The automated suite does not claim to test real apt upgrades, systemd boot persistence, kernel BBR behavior, UFW/nftables packet processing, provider firewalls or Shadowrocket/v2rayN GUI imports.

On a disposable Ubuntu/Debian VPS, verify all three installation modes, real certificate chain validation, trusted self-signed client imports, IPv4 hopping through UFW and cloud security groups, weekly timer execution, restart/restore failure handling and reboots. Keep provider console access and a snapshot throughout. These checks should precede production rollout.

## Shadowrocket follow-up

Added per-protocol separators, translated trust notes, PEM/DER public certificate exports and iOS root profiles for CA certificates. Profiles contain no passwords or private keys. Leaf-only certificates do not get root profiles, and stale trust exports are removed. Existing server certificates and credentials are preserved.

Menu 4 → 9 checks configuration, service, actual UDP listener, certificate identity/key/expiry and UFW. It prints timeout/auth/trust guidance without printing node passwords. Tests cover profile schema, public DER content, CA-versus-leaf behavior, translated separators, changed ports and stopped services.

User evidence confirms an active sing-box service and a UDP 443 listener. This does not establish external UDP reachability or client TLS trust. Shadowrocket screenshots show TLS enabled but not its inner trust settings. The user later reported working connectivity; the exact cause of the earlier failure was not established.

## Managed uninstall

Menu 6 → 3 requires confirmation and a successful backup before removing owned services/files. Tests cover cancellation, changed unit ownership, symlinked binaries, backup/stop failures, auxiliary service cleanup, script-copy identification and retention of external certificates, unrelated files, unowned hopping tables and backups. System mutations are mocked in these tests; no development-host or production VPS services are actually uninstalled.

## Client-specific exports

Terminal sections show v2rayN URIs, full Clash Verge/Mihomo YAML, full sing-box client JSON and Shadowrocket local Base64 subscriptions, each separated with dashed lines. Legacy exports remain. New exports are private files, carry only installed protocols, retain verified TLS trust and are removed during managed uninstall. YAML/JSON are checked by actual Mihomo/sing-box binaries for all three protocol combinations. Real HY2 forwarding tests now load the complete generated client configurations, rather than constructing their own client routing. No Shadowrocket/v2rayN GUI compatibility claim is made.

## Custom names and output colors

Installation and menu 2 → 3 accept a persisted node-name prefix, defaulting to SKYBYTE on Enter. Protocol suffixes keep names unique. Tests cover Chinese/spaces/URI punctuation, all exported names and routing references, unchanged server config, reset to default, length/control-character rejection and real engine config validation. Node metadata and instructions use yellow ANSI styles while credential/config content stays red; NO_COLOR/non-terminal output remains plain.

## Argo and grouped menus

58 tests cover both tunnel modes, token-file privacy, registration/address lifecycle, removal/backup/restore, ownership guards, download verification, unchanged credentials and bilingual grouped dispatch. Actual sing-box and Mihomo clients passed local verified TLS/WebSocket forwarding. A separate live Quick Tunnel check with cloudflared 2026.10.0 passed HTTPS/WebSocket forwarding. The local resolver returned NXDOMAIN for the new hostname; public DNS supplied the address while original SNI/Host and TLS verification were retained. Named account routes were not live-tested. Systemd mutations are mocked; VPS startup and graphical client imports remain deployment checks.

## Shadowrocket terminal QR codes

60 local tests passed. New tests verify that each exact exported Shadowrocket URI is fed to qrencode through stdin, separated and named in the terminal, with no credentials in encoder arguments; encoder failure is propagated and the bilingual submenu dispatches the new action. The QR renderer is mocked in these regression tests; physical phone scanning has not been tested. bash -n, ShellCheck and git diff --check passed.

## Shadowrocket native VLESS links

62 tests passed locally. Dedicated native exports preserve standard exports; roundtrip checks cover Base64 authority, Unicode/punctuation names, Vision, Reality public key/short ID/fingerprint, WS host/path and enabled certificate verification. QR input tests now use native files. Schema follows the Xboard Shadowrocket exporter linked in both READMEs; actual Shadowrocket GUI import/scanning still needs user verification.

## Startup summary

64 tests passed locally. The bilingual green startup summary reads local OS/kernel/architecture/virtualization/interface addresses and checks real service state, with fallbacks for missing probes. Tests cover translated output, running/inactive/uninstalled distinctions and lack of startup network requests. New changes are consolidated into PR #7.

## Per-account quotas and expiry

New accounts use isolated official sing-box instances with loopback authenticated Clash controllers. Actual Reality (with a local TLS 1.3 decoy) and HY2 forwarding are metered. Tests verify independent credentials/ports/totals, upload and download accounting, live reset without recounting old bytes, quota exhaustion while another account continues, persisted totals after supervisor restart, expiry rejection, controller failure and corrupted-ledger shutdown. Additional cases cover account caps, disabled/deleted records, atomic creation failures, private files/exports, current-policy/usage retention on restore, ownership/symlink safeguards, bilingual dispatch, firewall rules and hopping conflicts. Existing admin/Argo nodes are deliberately outside account quotas.

Validation uses the bundled Python with TLS 1.3 for the Reality decoy test; older Apple Python skips that test. Enforcement is periodic and not byte-exact: sampling/shutdown/crash gaps and traffic overshoot remain practical limits. Systemd/UFW/nftables mutations are mocked; live VPS deployment and graphical client imports remain user checks.

Local result: 80 tests passed with the bundled Python/TLS 1.3 runtime, sing-box 1.14.3 and Mihomo 1.19.32. bash -n, ShellCheck 0.11.0 and git diff --check passed. User live tests bind proxy and controller listeners only to loopback.

## V2.3 manager operations

93 tests passed locally. The additional operations suite verifies current module/bundle consistency and rootless self-check, stable release metadata and asset digest rejection, owned/atomic script updates with untouched node configuration/usage, rollback when the active supervisor cannot restart, independent quota/validity edits, safe fault diagnostics and validated recovery, direct main-menu access, scoped process/RSS reporting, expiry warnings, fingerprint-based domain-certificate reload selection, manual self-signed handling, certificate/key synchronization and client export regeneration, mismatched key rejection, and opt-in owned certificate timers. The real controller failure test additionally verifies persisted authentication reasons and secret-free diagnostics.

The source modules are assembled with `python3 scripts/build.py`. CI requires `python3 scripts/build.py --check`, bundle `--self-check`, Bash syntax checks for every source shell file, ShellCheck of the complete installer/bundle, and the full test suite. Keys and passwords are generated in temporary fixtures; no customer data is checked in. Release network responses, systemd service updates and resource snapshots use mocks; cryptography and filesystem operations are real. Actual VPS renewal hooks, service restart/rollback, daily timer execution and resource capacity still require deployment validation.

## V2.3.1 interaction styling and exports

93 tests passed after centralizing interactive prompts and selection hints, including unchanged confirmation/input behavior and native-link/QR exports. Updated export checks require the native Shadowrocket section and reject the removed duplicate Base64 display section. A manual pseudo-terminal check verified bold green prompts/options, reset before typed input, hidden token entry, mixed-case YES, and NO_COLOR plain output. Compatibility files remain on disk. All Bash source syntax, generated-bundle consistency and ShellCheck checks passed.
