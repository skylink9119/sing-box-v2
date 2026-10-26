<!-- SKYBYTE_AFFILIATE_HEADER_START -->
## VPS provider affiliate links

### 1. Residential IP landing VPS for cross-border e-commerce / TikTok

**[LisaHost](https://lisahost.com/aff.php?aff=11072)**: residential / ISP IP plans to consider for cross-border e-commerce, TikTok and overseas account workflows. Pair a residential landing VPS with this script's relay: the entry VPS handles client connections and the landing VPS reaches websites. Choose the two routes based on your network tests.

### 2. Premium-route VPS for personal use / sharing / relay entry

**[DMIT](https://www.dmit.io/aff.php?aff=18635)**: offers China-optimized network plans, including CN2 GIA options, for primary nodes, sharing with friends and relay entry servers.

**[BandwagonHost](https://bandwagonhost.com/aff.php?aff=83101)**: offers VPS plans including CN2 GIA options to consider for daily personal use or a relay entry server.

### 3. Budget VPS for learning / backup nodes

**[RackNerd](https://my.racknerd.com/aff.php?aff=18647)**: check budget VPS and annual offers for learning Ubuntu/Debian reinstalls, deploying sing-box / Hysteria2 and running backup nodes.

**Affiliate disclosure:** Purchases through these links may earn the author a commission to support SKYBYTE Manager development and maintenance. Pricing, routing and IP type depend on the selected plan; test speed and platform access from your own network.
<!-- SKYBYTE_AFFILIATE_HEADER_END -->

---

# SKYBYTE Manager V2.8.8 — sing-box Installer and Ubuntu/Debian VPS Management

**SKYBYTE Manager** is a Bash-based Ubuntu/Debian VPS manager with Simplified Chinese and English interfaces. It installs sing-box with **VLESS + Reality + Vision, Hysteria2 (HY2), or both protocols**, manages Cloudflare Argo tunnels and WARP routing, and provides per-user traffic quotas and expiry. Client exports support Shadowrocket, v2rayN, Clash Verge/Mihomo/OpenClash and sing-box JSON.

YouTube: [SKYBYTE9119](https://www.youtube.com/@SKYBYTE9119) · [中文](README.md)

If you find this script helpful, please subscribe to my YouTube channel and support SKYBYTE's continued development!

The main menu includes the SKYBYTE ASCII logo. Menus are bold green, credential links bold red, warnings bold yellow and errors bold red on ANSI terminals. Set `NO_COLOR=1` to disable colors. Every action uses `[y/N]`: type `y` or `Y` to confirm; Enter or `n/N` cancels.

V2.8.8 adds **Reality handshake target checks (d → 12)** for configured or custom targets, reporting DNS, TCP, TLS 1.3, certificate and HTTP/2 results.

V2.8.8 uses main-menu letters `a–g` (case-insensitive), numeric submenus, `0` to return one level and `q` to exit. Completed, cancelled and failed operations keep the current menu open. For example, `d → 2` lets you install, enable and inspect UFW consecutively. Idle menus release the operation lock. Previous main-menu numbers remain compatibility aliases.

V2.8.6 fixes literal `\n` text in WARP menus. One option per line, grouped as proxy setup (1–3), routing (4–6) and connection tests (7–8), with readable localized status. Confirm with `y` or `Y` at `[y/N]`; Enter cancels.

V2.8.3 fixes first installation on minimal VPS images without `curl`: the new bootstrap checks for curl and installs it with CA certificates when missing, then starts the installer. APT or download failure stops the operation while preserving input for the language prompt and menus. Copy the complete updated installation command below.

V2.8.1 whole-source audit fixes: the installer checks ownership and atomically publishes the manager, rejecting symlinks and concurrent operations. Restore journals original files privately, rolls back files/service states on failure, and preserves unrelated configuration files. User allocation reserves inactive managed ports and inherits the actual listener family. Node-edit rollback reloads the original admin config; offline selection survives menu actions; standalone Argo certificate issuance no longer prompts to configure absent HY2. Initial generation passes UUIDs, passwords and private keys through a file descriptor instead of process arguments. Media results show region sources/conflicts without claiming account eligibility or playback.

## Quick navigation

- [Ubuntu/Debian VPS installation](#ubuntudebian-vps-installation)
- [Menu and features](#menu-and-features)
- [Hysteria2 / HY2 and verified TLS](#hysteria2--hy2-and-verified-tls)
- [Cloudflare Argo Quick / Named Tunnels](#argo-quick--named-tunnels)
- [Restricted networks: Argo rescue, IPv6 and NAT](#restricted-networks-argo-rescue-ipv6-and-nat-v28)
- [Account limits, traffic quotas and expiry](#account-limits-traffic-quotas-and-expiry)
- [WARP egress and dual-stack](#warp-egress-and-dual-stack-v24)
- [Personal HTTPS subscriptions](#independent-https-subscriptions-v25)
- [Residential IP landing and VPS relay](#residential-ip-landing-and-vps-relay-v26)
- [HAProxy TCP passthrough](#haproxy-tcp-passthrough-v27)
- [Source modules and build](#source-modules-and-build) · [Validation](#validation)
- [FAQ](#faq) · [VPS provider affiliate links](#vps-provider-affiliate-links)

## Ubuntu/Debian VPS installation

Requires root, Ubuntu/Debian and systemd. Log in as root and paste this single command into Bash. When curl is missing, it is installed together with CA certificates; the bootstrap script handles the remaining checks.

<!-- SKYBYTE_INSTALL_COMMAND_START -->
```bash
(if ! command -v curl >/dev/null; then apt-get update && apt-get install -y curl ca-certificates; fi && script=$(curl -q -fsSL --max-time 60 https://raw.githubusercontent.com/skylink9119/sing-box-v2/main/bootstrap.sh) && bash -c "$script")
```
<!-- SKYBYTE_INSTALL_COMMAND_END -->

[`bootstrap.sh`](bootstrap.sh) handles detailed system checks, error messages and temporary-file cleanup. Installation or download failure stops execution, while input remains available for the language prompt and menus. Working APT repositories are required when curl is missing.

Until the development branch is merged, that command installs the main version. To test this branch, clone the repository, switch to the branch and run `bash ./singbox-v2.sh` as root. Review downloaded scripts before execution.

The entry point updates only identifiable SKYBYTE Manager files and preserves the current copy on download/validation failure. The installation directory, target script and operation lock must not be symlinks. Retry after any active management operation completes.

After installing/updating, log in again and run **`sb`** to open the main menu. The owned `/usr/local/bin/sb` launches SKYBYTE without arguments; `sb filename` still delegates to the original `/usr/bin/sb` file sender. Foreign same-name launchers and symlinks are preserved. Run `hash -r` or reconnect if the current shell cached the old command. Uninstall removes only the owned shortcut.

**Debian 11/12 compatibility:** refresh APT indexes strictly, permit authenticated Suite-only changes, abort on index errors, and retry package download failures once after another refresh. Bullseye archive repair supports legacy `.list` and deb822 `.sources`, backing up originals under `/etc/apt/skybyte-source-backup.*`. Existing HTTP/HTTPS transport, Signed-By, third-party repositories and custom mirrors are preserved. Only archive entries disable metadata expiry checking; package signatures and HTTPS verification remain enabled. Debian 12/13 are not redirected to the archive. HY2 self-signed generation uses an isolated request configuration to avoid duplicate certificate extensions in OpenSSL 1.1.1 on Debian 11, for both fresh installation and protocol additions; TLS verification remains enabled. Debian 11 official LTS has ended; historical packages do not restore security maintenance. See [Debian lifecycle](https://www.debian.org/releases/bullseye/) and [official archive](https://www.debian.org/distrib/archive).

Fresh installation uses the official sing-box 1.14.3 binary tested for this manager release and verifies its SHA-256 digest against GitHub Release metadata. It does not run a remote package installer. Choose a language at first launch; it is saved in `/etc/singbox-v2/language.conf`. Menu **f → 1** changes language.

**Installation refuses to overwrite an existing configuration, manager state, sing-box binary, service or occupied protocol port.** Manage an existing deployment through 1 → 5. Fresh installation stages and validates files before committing; failures remove only files created by that attempt, allowing retry without replacing existing files. Management/updates preserve credentials. New deployments use TCP 443 / UDP 443. Configure the provider firewall separately.

## Menu and features

| Menu | Category | Functions |
| --- | --- | --- |
| a | Install nodes | Reality / HY2 / dual; Quick / Named; node edits / protocol changes; restricted-network setup |
| b | Nodes and subscriptions | Information / exports / custom names / QR codes / accounts / personal HTTPS subscriptions |
| c | Services and logs | Controls / logs / Argo status |
| d | Server and network | Initialization / UFW / firewall / BBR / hopping / traffic / resources / media / WARP / sing-box relay / HAProxy TCP passthrough / Reality target checks |
| e | Updates and backups | Core versions / backup / restore / manager updates / certificates / ACME / encrypted backups |
| f | Settings and uninstall | Language / privacy / uninstall / guide |
| g | Users and quotas | Accounts / usage / quota / expiry / diagnostics / resources |
| q | Exit | |

Initialization updates apt indexes, upgrades packages, installs administration tools and checks time synchronization, DNS, HTTPS, SSH and UFW. It preserves an active time-sync service and does not enable UFW, change SSH, configure BBR or reboot. Package upgrades may restart services; retain console access.

Before enabling UFW, the manager detects SSH ports from sshd listeners, `sshd -T` and `SSH_CONNECTION`, then asks you to verify the port. Detected ports and the verified port are allowed, together with deployed protocol ports and active HY2 hopping ranges. Menu d → 3 audits the configured HY2 UDP port and hopping range rules. Complex UFW rules require manual inspection; provider security groups cannot be inspected by this script.

vnStat reports **total VPS interface traffic**, never separate Reality/HY2 traffic. History starts when vnStat begins collecting data.

## Reality handshake target checks

Open **d → 12**: **1** checks Reality targets from the current configuration; **2** checks a custom target. Enter a hostname or `host:port` (default 443), then an optional separate SNI; Enter uses the target hostname. Duplicate target/SNI pairs are checked once. Custom checks work before Reality is installed.

Results show DNS, the connected TCP address, TLS 1.3, certificate trust / validity / hostname, HTTP/2 ALPN and a clear PASSED / FAILED summary. Each target has a 12-second total network budget. Failures explain the cause without disabling certificate verification. The menu stays open; `0` returns one level.

Checks cover **this VPS → target** only. They do not edit nodes, credentials or routes, restart services, or verify client, public node-port or CDN connectivity. Healthy targets do not need scheduled rotation; investigate or change them when a check fails.

## Hysteria2 / HY2 and verified TLS

Installation accepts a node name prefix; press Enter for `SKYBYTE`. Existing deployments can use menu **b → 3**. Exports append `-Reality` or `-HY2` to avoid duplicate protocol names. Names support up to 64 characters, including Chinese, spaces and ordinary symbols; URI fragments are percent-encoded. All client formats use the same names. Renaming preserves server configuration, UUIDs and passwords and does not restart the service. Node names, client headings, file paths and instructions use bold yellow on color terminals; links and configuration contents remain red.

Choose either:

- **No-domain self-signed certificate:** generates a certificate with the actual public IP SAN (IPv4 or IPv6), valid for 365 days. Clients must trust its public certificate.
- **Managed ACME:** issue a domain certificate through isolated Certbot state; automatic renewal is opt-in, as described below.
- **Existing TLS certificate:** supply its domain, full certificate chain and private-key paths. Installation checks expiry, hostname/IP and key matching. The chain must also be trusted by clients. Supplied files are not modified.

Server and client passwords match; URI credentials are percent-encoded. Certificate verification stays enabled. Self-signed certificates are not trusted by default, so importing only a URI is insufficient.

Menu b → 2 exports:

| File | Purpose |
| --- | --- |
| `v2rayn-nodes.txt` / `v2rayn-subscription.txt` | v2rayN URIs / local Base64 subscription; verify core support and certificate trust |
| `shadowrocket-nodes.txt` / `shadowrocket-subscription.txt` | Shadowrocket URIs / local Base64 subscription content; local files by default; opt-in personal HTTPS delivery is available |
| `clash-verge.yaml` | Complete Clash Verge Rev/Mihomo local configuration, including a proxy group and routing; loopback mixed port 7890 |
| `sing-box-client.json` | Complete sing-box client JSON, with loopback mixed port 1080 and the first node as its default route |
| `nodes.txt` / `subscription-base64.txt` | Shadowrocket/v2rayN and other compatible clients; verify TLS trust after import |
| `mihomo-proxies.yaml` | Mihomo/OpenClash fragment; merge both `proxies` and the self-signed `tls.custom-certifactes` trust settings (upstream spelling) |
| `outbounds.json` | sing-box JSON fragment containing `outbounds`, to merge into a client configuration |
| `hy2-client-ca.pem` | Self-signed public certificate for manual trust setup |
| `hy2-client-ca.cer` / `hy2-client-ca.mobileconfig` | DER public certificate / iOS trust profile; profiles are generated only for CA certificates and require manual installation/trust |
| `subscription-notes.txt` | Trust instructions, SHA-256 fingerprint and hopping notes |

Installed protocols are detected from the actual `config.json`. Self-signed sing-box exports embed the public certificate. Mihomo exports embed trusted certificates and a fingerprint, with `skip-cert-verify: false`. HY2 URIs include `insecure=0` and the self-signed fingerprint. URI pinning, custom CA trust and hopping support vary by client/core version.

For Shadowrocket/v2rayN, retrieve `hy2-client-ca.pem` over trusted SSH/SFTP. Run `openssl x509 -in /etc/sing-box/hy2-selfsigned.crt -noout -fingerprint -sha256` on the server and verify the fingerprint through a trusted channel. Import the certificate using the trust mechanism supported by the client/core, keeping verification enabled. If the client cannot trust a custom CA, use an existing certificate issued by a trusted CA. **Never transfer or import the server private key.**

Exports contain credentials, remain local under `/etc/singbox-v2/` and use mode 600 inside a mode-700 directory. No public subscription service is created by default; HTTPS delivery requires separate setup. Never publish exports in repositories or issues. Restart the service after certificate renewal/replacement; after replacing a self-signed certificate, re-export and update client trust.

## Hopping, updates and restore

Node information is grouped into v2rayN, Clash Verge/Mihomo YAML, sing-box JSON and Shadowrocket native link sections with dashed separators. The terminal displays URIs, complete YAML/JSON and file paths; the duplicate Shadowrocket Base64 display section is removed. Compatibility subscription files remain local. Import full configurations as new local client profiles; existing client configurations are not overwritten. sing-box uses the first node by default; change `route.final` to another outbound tag when needed. Use Mihomo rather than classic Clash, which does not support these protocols. URI/Base64 formats remain compatible; online URLs use the separate opt-in HTTPS feature.

**No domain does not mean no certificate.** Default URIs retain `insecure=0`. Importing a URI does not establish self-signed certificate trust, and enabling TLS does not establish trust.

On iPhone, install `hy2-client-ca.mobileconfig`, then enable full trust under **Settings > General > About > Certificate Trust Settings**. Install only a certificate securely obtained from your own VPS via SSH/SFTP after verifying its fingerprint. This profile adds system root trust; remove it when no longer needed. It contains no node password or private key. Root profiles are not generated for leaf-only certificates, and existing server certificates are preserved. System trust does not prove Shadowrocket HY2 uses that trust store; verify with connection logs. Use a trusted CA certificate if unsupported. See [Apple certificate trust instructions](https://support.apple.com/en-us/102390).

The former IP information, basic network and HY2/Shadowrocket diagnostic menu entries have been removed. A local listener does not prove provider/mobile-network UDP reachability. Use actual connections or URL tests in Shadowrocket; ICMP latency does not validate HY2.

Hopping is off by default, under **d → 5**, with nftables (default) or iptables. The default range is `20000–40000`; ranges within 1024–65535 may contain at most 20001 ports. IPv4 UDP maps to the actual HY2 listener. Only the dedicated `ip singbox_v2_hop` table or `SKYBYTE_HY2_HOP` NAT chain is used. Existing named rules and account HY2 port overlaps are rejected. systemd persists rules and active UFW permits the range. sing-box/Mihomo exports include the range and a 30-second interval; basic URIs retain the base port. Allow the range in your provider firewall. Disabling hopping leaves UFW rules for manual cleanup to avoid deleting rules used by other applications. Hopping does not guarantee relief from throttling or UDP blocking; providers must allow the range.

Updates back up first, download and check a candidate binary, then replace the binary, restart and check service health. Startup failures restore the previous binary. Manual updates require confirmation. Weekly automatic updates have been removed. Startup backs up and retires owned legacy update units, preserving modified or unowned units. Service health alone does not prove client connectivity.

New backups use separate `config/`, `state.json` and `sing-box.bin` paths, including external TLS certificate/key snapshots. Restore backs up the deployment and journals original file contents/modes privately, publishing each managed config/certificate/binary atomically. Failure rolls back files and original service activity/boot states; incomplete rollback is reported with retained transaction/backup paths. Unrelated configuration files are preserved. Success refreshes client exports and disables managed hopping; re-enable it when required. Other nftables tables are untouched. The old broken directory/binary backup layout is not directly supported. Backups are not automatically pruned; protect disk space and private keys.

## Validation

Menu **f → 3** requires case-insensitive `y` confirmation and first backs up configuration, certificates and the binary. Backup failure cancels removal. It stops automatic updates, managed hopping and sing-box, then removes owned units, the binary, node configuration, generated certificates/exports and identifiable manager executable copies. Changed unit ownership/start paths or symlinked key files cause refusal. Successful uninstall exits the menu.

Backups, external certificates, unknown user files, reports, UFW allow rules, BBR/FQ settings and system packages such as vnStat remain. It does not reset the firewall or delete unrelated nftables tables. Backups contain private keys; protect permissions and disk space. To restore after uninstall, deploy again and restore the retained backup through menu e → 3.

```bash
for file in bootstrap.sh install.sh singbox-v2.sh src/*.sh; do bash -n "$file"; done
shellcheck bootstrap.sh install.sh singbox-v2.sh
python3 -m unittest discover -s tests -v
```

Set `SING_BOX_BIN` and `MIHOMO_BIN` to include real engine validation: all three server modes, Mihomo YAML parsing, and local forwarding through HY2 with sing-box/Mihomo clients. Mihomo tests require PyYAML. Credentials and certificates are generated in temporary directories and are never committed.

Local tests require Python 3.9+, PyYAML and OpenSSL with `x509 -checkhost/-checkip`. The old macOS system LibreSSL is unsuitable; select OpenSSL 3 through `OPENSSL_BIN` and the executable search path. Set `HAPROXY_BIN` for real TCP passthrough tests. Tests requiring unavailable protocol engines, HAProxy or GnuPG are skipped, which does not establish that functionality was verified.

GitHub Actions runs checks in Ubuntu 24.04 and Debian 11, 12 and 13 containers. See [audit and testing notes](docs/TESTING.md). Local handshakes do not replace live VPS tests of provider firewalls, UDP NAT, systemd startup or Shadowrocket/v2rayN GUI imports. Validate these on a disposable VPS with snapshots and console access.

## Privacy, legal notice and references

For lawful networking education and server administration, subject to applicable law and service terms. Optional ACME contacts Let's Encrypt and Cloudflare for DNS validation; public certificates disclose hostnames. HTTPS delivers personal credential exports to token holders. Installation/updates contact GitHub and api.ipify.org/api64.ipify.org; media tests contact the selected platforms, and WARP installation/verification/DNS contact Cloudflare. These services see the egress IP and request metadata. WARP forwards selected user traffic through Cloudflare. No developer telemetry or credential uploads. Reports remain local; manage retention yourself. Provided as-is; back up before deployment.

- [sing-box HY2](https://sing-box.sagernet.org/configuration/outbound/hysteria2/)
- [sing-box TLS](https://sing-box.sagernet.org/configuration/shared/tls/)
- [Hysteria URI scheme](https://v2.hysteria.network/docs/developers/URI-Scheme/)
- [Mihomo TLS](https://wiki.metacubex.one/en/config/proxies/tls/)

## Argo Quick / Named Tunnels

Menu **a → 4** adds a separate VLESS + WebSocket node to an existing managed Reality/HY2 deployment. The origin listens only on loopback; existing credentials and configuration are preserved. All client exports use verified HTTPS/WSS. Cloudflare terminates outer TLS and can inspect WebSocket payloads.

Quick mode needs no account/domain; restart changes the hostname, requiring refreshed imports. [Cloudflare documents Quick Tunnels as testing services without uptime guarantees](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). Named mode requires a remotely managed tunnel and published hostname configured in your account: route HTTP to `http://127.0.0.1:8080` (use your selected local port), enable WebSocket support, and avoid interactive Access login. Enter hostname and Token locally; account DNS/routes are not provisioned by this script.

Controls include status/start/stop/restart/refresh/removal. Registration does not establish end-to-end reachability. Disconnected Quick nodes are omitted. Tokens use mode 600 and `--token-file`, are excluded from exports, and included in private backups. Removal preserves account tunnels/DNS. Restore re-registers before export. Official cloudflared downloads are SHA-256 verified.

Menu **b → 4** displays one Shadowrocket node QR code per installed/exportable node, separated by dashed lines. Scan with Shadowrocket. The manager installs Ubuntu/Debian package `qrencode` when needed; links are encoded locally through stdin and no QR images are saved. Self-signed HY2 still requires certificate trust; keep QR codes private.

Shadowrocket native links are additionally saved in `shadowrocket-native-nodes.txt`, with a Base64 list in `shadowrocket-native-subscription.txt`. VLESS uses Base64 authority plus native remarks/peer/xtls parameters, following the [Xboard Shadowrocket exporter](https://github.com/cedar2025/Xboard/blob/master/app/Protocols/Shadowrocket.php). Menu b → 4 encodes these links. Standard files remain unchanged; HY2 keeps its existing verified-TLS URI. Native links have not been GUI-tested in Shadowrocket.

## Restricted networks: Argo rescue, IPv6 and NAT (V2.8)

Open **a → 6** for an Ubuntu/Debian host with blocked inbound access, IPv6-only connectivity, or provider-managed NAT. This cannot restore SSH, repair host networking, or recover a machine with no usable outbound path. The VPS still needs access to required downloads and outbound Cloudflare connectivity. If the host is unreachable, first use the provider console or rescue environment.

- **1 / 2: standalone Argo Quick / Named Tunnel.** With no existing managed installation, the manager stages an empty sing-box core without public listeners, then creates a VLESS + WebSocket origin bound only to `127.0.0.1`. It provides a proxy entry while Cloudflare egress works; it does not carry HY2/QUIC. Quick Tunnels need no domain, but their hostname changes. Cloudflare classifies them for testing and provides no SLA, stable hostname or production guarantee. Named mode requires you to configure a Cloudflare Tunnel, published hostname and route to the selected loopback port; the script does not create DNS or account resources.
- **Add a direct node after standalone Argo:** open **a → 5 → 4**, choose Reality or HY2, then enter the public client address, local bind family and port. The separate Argo tunnel remains installed. Standalone Argo alone cannot host quota-managed accounts; add a direct node before enabling account management.
- **3 / 4: IPv6, custom ports and NAT.** Custom deployment lets you choose local ports/bind family and the address advertised to clients. The NAT export option separates the administrator node's public mapped ports/address from its local listener ports. Your provider must create the TCP/UDP mappings and allow the ports; the script cannot configure provider NAT, security groups or routes. Quota-user ports are not included and need separate mappings. HY2 certificate identity must match the name clients use to connect.
- **5 / 7: Cloudflare transport and reachability check.** Tunnel egress requires UDP 7844 (QUIC) or TCP 7844 (HTTP/2); HTTP/2 does not use TCP 443. The check tests only TCP 7844 reachability for the selected address family. It cannot prove UDP reachability, tunnel registration or end-to-end client connectivity. Choose the family and transport allowed by the VPS/provider egress rules.
- **6: WARP dual-stack completion.** Import your own working WARP WireGuard profile. The manager creates a gateway for managed node traffic and lets you select global WARP or WARP for selected media/AI domains. It leaves the system default route unchanged and cannot create its own first network path. The native Peer Endpoint must be reachable over the current network; IPv6-only hosts need a reachable IPv6 Peer Endpoint. Dual-stack checks verify only the gateway's IPv4/IPv6 TCP egress and do not promise service unlocking.
- **8: offline official assets.** On a trusted network, obtain the official sing-box/cloudflared Release assets for the CPU architecture and their GitHub Release API metadata, then copy them into one absolute-path directory. The manager verifies SHA-256 against that metadata and extracts only the target binary; obtain the metadata through a trusted channel too. Offline assets do not contain Debian/Ubuntu packages: dependencies must already be installed or the VPS must still reach its OS package repository.

Official asset mappings cover amd64, arm64, armv7 and 386; this does not guarantee compatibility with every old kernel or extremely small machine. cloudflared, sing-box, WARP gateways and quota users consume resources. Enable only what you need and watch memory. Private configs/backups remain under `/etc/singbox-v2/`; never publish credentials or private keys.

Interactive startup and language changes show a bold green version/system summary: OS, kernel, architecture, virtualization, local IPv4/IPv6 interface addresses and service installation/running state. No startup geolocation request is made; the IP information entry has been removed. Missing optional probes do not prevent opening the menu.

## Account limits, traffic quotas and expiry

Open **main menu g** (legacy **b → 5** remains), initialize management (default 10 accounts, configurable 1–100), then add accounts with a name, total upload-plus-download quota in GiB and validity days. Controls include per-account upload/download/total usage, quota/validity edits, enable/disable, deletion, explicit usage reset, personal exports and Shadowrocket QR codes. Expired or exhausted accounts lose their listeners and existing connections. Renewal does not reset usage automatically.

The limit counts undeleted accounts, including disabled/expired ones; it does not count actual people or prevent credential sharing. Quota edits retain expiry; validity edits retain quota and usage. Validity starts at creation or validity edit and is displayed in UTC. There is no automatic billing-cycle reset; `1 GiB = 1024³ bytes`.

Quota-managed accounts support **Reality + Vision, HY2 or both**, matching the installed admin protocol combination. Each gets independent credentials, an isolated sing-box process and free port, sharing the VPS egress IP. A dual account's protocol traffic is combined. Existing admin configuration/credentials remain **outside account limits, quotas and expiry**. Argo is not included in quota-managed accounts. Give users their personal nodes, not admin credentials.

Accounting reads cumulative totals from each isolated instance's [Clash API](https://sing-box.sagernet.org/configuration/experimental/clash-api/), never vnStat or VPS-wide totals. Every controller binds to `127.0.0.1` with its own secret. Admin and account services have separate start/stop controls; full uninstall stops all owned services.

Enforcement is periodic, usually around one second and longer under load; it is not a byte-exact hard cap. Overshoot depends on transfer rate and polling delay. Sampled totals are atomically persisted across restarts. Unsampled bytes may be lost during power failure, forced termination or the final shutdown window. An unavailable controller, invalid counters or unexpected child exit blocks the affected account until explicitly re-enabled after repair; damaged ledgers close quota-managed nodes. This is suitable for personal quota administration, not precise billing. Each account consumes additional memory, CPU and ports; set limits for your VPS capacity.

Personal files live in `/etc/singbox-v2/users/<account-ID>/`, with existing client formats and Shadowrocket QR support. Share only required **client exports**; never share `server.json`, `state.json`, `private.key`, `users.json` or backups. Files are mode 600 and directories 700. No hosted subscription service is enabled by default; optional HTTPS uses independent tokens for personal exports.

Active UFW permits account node ports; enabling UFW later includes existing accounts. Permit actual TCP/UDP node ports in provider security groups yourself and keep controller ports private. Allocation avoids enabled HY2 hopping ranges; new hopping ranges cannot overlap account HY2 ports. Account nodes do not use admin hopping rules. Deletion/uninstall leaves UFW rules for manual cleanup.

Backups include policies, usage, configurations and certificates. Restore retains current accounts and their latest policies/usage instead of rewinding counters or reviving deleted records, and preserves supervisor pause state. Older backups without account data keep current accounts. Updates validate account configs and restart previously active account services. The systemd supervisor is `skybyte-users.service`; limited private error logs for the current run are stored as `core.log` in each account directory.

## Manager operations (V2.3)

- **e → 1** updates the sing-box core; **e → 4** checks/updates SKYBYTE Manager itself. Manager updates use the latest stable GitHub Release asset, verify its SHA256, Bash/embedded Python syntax and version, and atomically replace owned script copies. Configurations, credentials and usage are retained. Script backups live in `/etc/singbox-v2/manager-backups/`. Previously active user supervisors, Argo tunnels and HTTPS subscription services briefly restart; failure rolls script copies back. Successful updates reopen the new menu. Development versions are not downgraded.
- **Main menu g** opens user management; the main menu shows account count/limit, ready accounts and supervisor status. **User menu 4** changes quota only, retaining expiry and usage. **13** changes validity from now only, retaining quota and usage. Resulting expiry is displayed in UTC.
- **User menu 14** reports safe failure categories, timestamps, exit codes, configuration checks and local log paths, without API secrets or raw logs. Authentication, timeout, invalid response, counter or core-exit failures stop the affected account. Repair the cause and explicitly enable it; enabling validates the core/controller configuration and does not bypass expiry or quota exhaustion.
- **d → 7** or **user menu 15** shows managed core/process counts, RSS memory, available system memory and load. RSS includes shared memory; this snapshot cannot guarantee account capacity.
- Startup shows HY2 certificate days remaining and warns within 30 days. **e → 5** checks expiry, synchronizes renewed certificates to user nodes and reloads previously active services, or enables/disables daily monitoring. Expired certificates and mismatched keys/identities are rejected.
- Daily monitoring is **off by default**, uses `skybyte-certificate.timer` and logs to systemd. It does not issue or renew certificates. A valid changed domain certificate at the configured paths is synchronized/reloaded. Renewal tools can call `/bin/bash /usr/local/sbin/singbox-v2 --certificate-reload` as a deploy hook. The first check establishes a fingerprint baseline; manually reload once if renewal happened before that baseline. Changed self-signed certificates require manual reload and updated client trust; TLS verification remains enabled.

## Source modules and build

Edit `src/quickstart.sh` (single-line installation command), `bootstrap.sh` (full bootstrap checks), `installer.sh` (entry point), `packages.sh` (APT/archive compatibility), `shortcut.sh` (`sb` launcher), `manager.sh` (base services/install), `subscriptions.sh` (exports), `users.sh` (user UI/services), `users.py` (accounting/diagnostics), `operations.sh` (updates/certificates/resources), `menu.sh` (menu/entry point), `rescue.sh`/`rescue.py` (restricted networks, Argo rescue, offline assets and IPv6/NAT helpers), `hopping.sh` (UDP hopping), `media.sh`/`media.py` (media probes), `warp.sh`/`warp.py` (gateway/owned routing), `relay.sh` (sing-box residential relay), `haproxy.sh`/`haproxy.py` (independent TCP passthrough), `configuration.sh`/`configuration.py` (node edits), `acme.sh` (issuance), `online.sh`/`online.py` (HTTPS delivery), `reliability.sh`/`backup.py` (transactions/versions/backups) and `help.sh` (guide). Run `python3 scripts/build.py` to produce the self-contained `singbox-v2.sh`, `install.sh`, `bootstrap.sh` and the bilingual installation commands; CI uses `--check` to reject stale bundles. Do not edit the generated bundle directly.

The original `install.sh` entry remains sufficient: deployed scripts contain all modules and require no runtime module downloads. `bash singbox-v2.sh --self-check` checks embedded Python syntax and outputs the version without root. systemd/UFW operations are tested through isolated mocks; actual VPS deployment still needs verification.

V2.3.1: interactive questions, selection hints and YES confirmations use bold green, reset before typed input. Hidden Token input remains hidden. Non-terminal and `NO_COLOR` output stays plain. Shadowrocket native links and QR codes remain available.


## WARP egress and dual-stack (V2.4)

Open **d → 9**: 1–3 set up proxies, 4 selects platforms, 5 switches modes, 6 manages rules, 7 tests dual-stack egress and 8 compares platform responses. WARP is disabled by default. Initial setup routes only media/AI domains through WARP, leaving other traffic direct. Select **direct / global WARP / restricted domains**, or supply custom suffixes. Defaults include the five media platforms plus major OpenAI/ChatGPT, Gemini and Claude domains and some CDNs. Remove AI suffixes in a custom list for media-only routing. Matching depends on domains and sniffing; literal IPs, ECH and unlisted CDNs may evade classification. WARP cannot guarantee platform unlocking or a chosen exit country.

WARP submenu **4** offers Netflix, Disney+, ChatGPT, Gemini, all four, all media/AI and custom suffix presets. Readiness retries verify the actual proxy after installation; existing WARP clients/data are retained. Trace checks validate WARP status, global IP and country. Gemini uses specific web/AI Studio/API domains, not all Google traffic.

Three gateway sources are supported:

- **Official WARP client**: signed Cloudflare apt repository, explicit terms confirmation, registration and local SOCKS5 proxy mode. Existing installations are preserved; use the existing-proxy option instead. Supported releases follow the [official repository](https://pkg.cloudflareclient.com/).
- **Existing local proxy**: requires a loopback-only SOCKS5 listener and actual Cloudflare trace verification of `warp=on/plus` before applying routes.
- **Existing WARP WireGuard profile**: import your own legitimately obtained dual-stack profile into one shared userspace sing-box gateway with TCP/UDP. No embedded profile scripts run and no WARP account is created automatically. Unsupported directives are rejected. Private keys stay in private server gateway configuration and never enter client exports.

Admin, Argo and quota-managed accounts share one local gateway; credentials and metering remain independent. Mode changes back up and validate all candidate configurations before restarting previously active nodes, with routing rollback on failure. Unmanaged custom routing is rejected. New users/Argo nodes inherit the current policy. System default routes are untouched. Selected WARP traffic fails when the gateway fails; it does not silently fall back to direct.

SOCKS5 UDP capability is probed. Unsupported matching UDP is rejected; application TCP fallback depends on the application. In global mode this affects all inner proxy UDP, while outer HY2 client-to-VPS UDP is unaffected. Native WireGuard TCP/UDP forwarding has local automated coverage. Dual-stack tests verify IPv4/IPv6 targets and actual trace address families separately. They test node TCP egress, not system-wide dual-stack. A gateway can provide an additional address family for node traffic.

IPv6 exports use bracketed URI authorities and valid IP SANs. IPv6-only bootstrap still requires access to GitHub, package repositories and registration endpoints, potentially through provider NAT64 or pre-existing egress. WARP cannot supply connectivity before its first download. Real Cloudflare egress requires deployment verification.

Backups include routing, private gateway configuration and owned units. Restore retains current account quotas, expiry and usage while reconciling routing. Uninstall stops/removes the managed gateway and preserves external source profiles. The official client is disconnected only when its registration fingerprint still matches; its package, repository and registration remain. Backups contain private keys; keep them private.

## Streaming availability tests (V2.4)

Open **d → 8** for Netflix, Disney+, ChatGPT, Gemini, YouTube Premium, Amazon Prime Video and TikTok. Choose direct IPv4, direct IPv6, WARP or an IPv4/WARP comparison. Anonymous official-page requests identify country/region fields, final-page locale hints and explicit location restrictions; the output names the field source and reports missing or conflicting clues. Requests use verified TLS, bounded timeouts/body sizes, no account login or cookies, and no remote third-party scripts.

Results distinguish page region clues, explicit location restrictions, catalog/subscription offers and connection failures. A page field or URL locale is only a clue; it does not prove the VPS egress country, a full catalog or playback. HTTP 200 confirms only a page response, not unlocking. 403/429, challenges and changed pages generally remain unknown; explicit unsupported-country/region errors from ChatGPT/Gemini are classified as location restrictions. No account login, payment eligibility or playback validation is performed; AI account availability is not tested. WARP uses proxy-side DNS and does not claim a specific egress address family.

Private reports contain classifications, region hints and HTTP codes, at `/etc/singbox-v2/reports/media-*.json`, mode 600. Raw pages and node credentials are excluded. Probes run on demand without background jobs. WARP and each user core add resource usage; **d → 7** shows process/memory/load snapshots, without a fixed account-capacity promise.


## Node editing (V2.5)

Open **a → 5** for independent admin Reality/HY2 ports, server IP/DDNS, Reality handshake identity, adding/removing protocols, HY2 bandwidth/Salamander options and existing TLS certificate changes. Removing the final protocol is refused. Added HY2 can generate a self-signed certificate or use an existing/managed ACME certificate; self-signed clients still require public-certificate trust.

All candidates are checked before backup, final account metering, commit and restart of previously active nodes. Failure restores the original files. Existing UUIDs/passwords, individual ports, quota/expiry and usage remain. Adding Reality generates its keypair; re-adding a removed Reality protocol may produce a new public key, requiring import refresh. Exports and active UFW rules follow actual ports; old rules remain and provider security groups need manual updates.

Active hopping is disabled after an edit; re-enable it for the current listener. DDNS changes connection addresses only, without provisioning/updating DNS. A valid config/active service does not prove every client's end-to-end connectivity.

HY2 options include upload/download Mbps, `ignore_client_bandwidth` and Salamander obfuscation. Ignoring client bandwidth requires both Mbps values to be zero. These are not cross-protocol per-account hard rate caps. Client exports follow server settings; refresh after obfuscation changes. TLS verification stays enabled.

## ACME certificates (V2.5)

Open **e → 6**, or select managed ACME during fresh HY2 installation. Distribution Certbot packages use isolated config/work/log directories under `/etc/singbox-v2/acme/`; no remote issuance scripts run and `/etc/letsencrypt/`/existing websites remain untouched.

- HTTP-01 needs correct A/AAAA records and public TCP80. Occupied port80 is rejected without stopping an existing site. Active UFW permits TCP80; provider rules remain manual.
- Cloudflare DNS-01 uses the packaged Certbot plugin. A scoped DNS token is entered hidden and saved mode600, excluded from command arguments, client exports and GitHub. Follow the [plugin permission guidance](https://certbot-dns-cloudflare.readthedocs.io/en/stable/).

CA terms require confirmation; public issuance discloses the hostname. Successful certificates may be used for HY2 or HTTPS subscriptions even on Reality-only servers. Failed attempts retain private logs; menu6 clears only an incomplete owned attempt for retry.

Auto-renewal is opt-in through `skybyte-acme.timer`, attempting twice daily in server time with up to one hour randomized delay. Certbot decides whether renewal is due. Valid changes synchronize HY2 user certificates and reload active HTTPS delivery; failures retain current certificates. An operation-lock conflict fails the attempt until the next interval; monitor expiry/logs. See [Certbot's guide](https://eff-certbot.readthedocs.io/en/stable/using.html).

## Independent HTTPS subscriptions (V2.5)

Initialize accounts and obtain a trusted domain certificate, then open **b → 6** for hostname, HTTPS port (default8443) and certificate paths. Setup checks identity, key matching, expiry and system chain trust. It does not default to self-signed subscription TLS or disabled verification. Point DNS to the VPS and allow the actual provider TCP port. The service directly serves HTTPS without configuring CDN/reverse-proxy/account DNS.

**User menu16** (or **b → 6 → 6**) issues, views, rotates or revokes an independent random token. Separate URLs deliver Shadowrocket, v2rayN, complete Mihomo YAML and sing-box JSON. Tokens are independent of node UUID/password; rotation immediately invalidates the old URL. Responses include upload/download/quota/expiry in `subscription-userinfo`; graphical client display remains a deployment check.

Only personal client exports are accessible: no directory listing, admin nodes, private keys, controller secrets or account database. Disabled/deleted/expired/exhausted/metering-blocked accounts, or paused supervisors, cannot download. Requests use current policy and regenerate exports under operation-lock coordination; busy edits may temporarily return unavailable. Responses prohibit caching, cap concurrency/rates and omit token-bearing request logs.

**URLs grant access to node credentials: keep them private. Revoking a token revokes downloads only; it does not rotate imported node passwords or terminate existing nodes.** Disable accounts through user menu5. Subscription HTTPS trust and HY2 node trust are independent; self-signed HY2 still requires explicit public-certificate trust.

## Versions, backups and rule maintenance (V2.5)

**e → 1** selects tested 1.14.3, latest stable, or a specified stable version/downgrade. Official releases are digest-verified and must validate every admin/account/Argo/native-WARP configuration. Configurations are not silently regenerated; startup failure rolls the core back. Weekly automatic updates remain removed.

**e → 7** lists/creates/preflights backups, exports/imports GnuPG AES256 passphrase-encrypted archives and explicitly prunes older managed backups. New snapshots include SHA256 manifests. Preflight uses the currently trusted engine, never the executable inside an imported archive. Import only your own trusted backups. Hidden passphrases use file descriptors, not process arguments; forgotten passphrases cannot be recovered.

Import rejects traversal, duplicate/oversized entries and symbolic/hard links. Restoration still requires separate confirmation through **e → 3**. Retention only affects backups with this manager's manifest; unknown/legacy directories remain and no automatic deletion occurs. Digests detect changes, not the authenticity of an unknown source. Backups contain private keys, DNS tokens and subscription tokens: protect files/passphrases.

Restore retains current account policy/usage and current subscription tokens. HTTPS certificate snapshots are saved separately; missing subscription/ACME state is filled only when absent, with rollback on failure and explicit renewal re-enabling. External TLS is restored as private config-directory snapshots; re-associate current ACME paths through the certificate menu to resume using those renewal paths. Uninstall first backs up, then removes owned HTTPS services, ACME tasks and private ACME directories, preserving external certificates/packages/backups.

**WARP menu6** verifies current egress, manually downloads a stable release's digest-verified catalog, and separately applies it. Failure keeps the previous list; downloading does not replace custom live routing. Releases must include the public `data/warp-rules.json` asset. Catalog version/source are visible, without an unlocking guarantee.

**f → 4** or `bash singbox-v2.sh --help` provides a bilingual quick guide. An idle main menu releases the operation lock so background renewal can run; active management operations remain exclusive.

```bash
python3 scripts/build.py --check
python3 scripts/package_release.py --output /tmp/skybyte-release-2.8.8
```

Packaging includes only bootstrap.sh, install.sh, the full bundle, public rule catalog and SHA256SUMS, never runtime state or credentials.

## Account scaling tests (V2.5)

Metering threads reuse their loopback HTTP clients and unchanged idle ledgers avoid needless writes. Active traffic retains the existing persistence cadence rather than trading away additional unsampled usage.

`scripts/benchmark_users.py` creates 10/30/50 real HY2 cores in disposable directories with loopback-only listeners, reporting readiness, sample age, RSS and Linux PSS when available. [Local idle results](docs/benchmarks/local-idle-v2.5.json) are macOS arm64 snapshots, not Ubuntu/Debian capacity guarantees. RSS includes shared mappings and idle CPU does not establish throughput. CI publishes Linux results separately. Regression tests cover actual forwarding, quota enforcement and concurrent sampling; measure production capacity under real workloads.

```bash
SING_BOX_BIN=/path/to/sing-box python3 scripts/benchmark_users.py \
  --engine /path/to/sing-box --counts 10,30,50 --output /tmp/account-benchmark.json
```

## Residential IP landing and VPS relay (V2.6)

Menu **d → 10: Residential landing / VPS relay**, then **6 Usage guide**, shows the setup steps and certificate-copy/fingerprint commands even before importing a landing node. It supports a residential-IP VPS with a poor direct route from mainland China by using an entry VPS with a better client-facing route:

**Copy the residential server's node URI into the entry server's manager. Your phone connects to the entry server.**

First identify the two servers:

- **A: entry server.** Your phone connects to A.
- **B: residential IP server.** B accesses websites; websites see B's residential exit IP.

**Both servers need working nodes.** Open a separate SSH terminal for each server. Keep B's egress direct to retain the residential exit; disable WARP routing on B if active. Allow B's actual node port from A: TCP for Reality, UDP for HY2, including the provider firewall.

1. **Open B's terminal.** Install **Reality + Vision** or **HY2** if needed; an existing working node is fine. In SKYBYTE Manager, select **b → 1 View nodes**. Copy one complete red URI beginning with `vless://` or `hysteria2://`.
2. **Switch to A's terminal.** Open **d → 10 Residential landing / VPS relay**. Select **1 Import / replace landing**, then **1 Paste node URI**.
3. **Paste B's URI and press Enter.** Hidden input displays no characters while pasting; this is expected.
4. **Handle the certificate prompt.** For Reality or HY2 with a trusted CA certificate, press Enter. For self-signed HY2 on B, copy **B's public certificate to A**, verify its fingerprint and enter its file path on A. See the certificate commands below.
5. **Choose `1 All node traffic through landing`, then type `y`.** Enter accepts the default mode. The script validates configurations and tests B's HTTPS connection and egress IP. Failure leaves existing routing; success backs up and restarts previously active admin/account/Argo nodes. Relay is enabled when import completes.

**Finally, Shadowrocket uses A's node URI or QR code.** If A uses self-signed HY2, Shadowrocket still needs to trust A's public certificate. Path after connecting:

```text
Shadowrocket → A entry server → B residential server → website
```

On A, select **2 Test landing**: the reported egress should belong to B's residential connection. Test actual access, uploads/downloads and latency on the phone.

**Only for self-signed HY2 on B: public certificate transfer.** Run on A over trusted SSH/SFTP (replace `LANDING_VPS_IP` with B's address; SSH defaults to port 22; for another port, add `-P` with that port to `scp`):

```bash
scp root@LANDING_VPS_IP:/etc/singbox-v2/hy2-client-ca.pem /root/landing-hy2-ca.pem
```

Compare SHA256 fingerprints through a trusted channel. Run on B:

```bash
openssl x509 -in /etc/singbox-v2/hy2-client-ca.pem -noout -fingerprint -sha256
```

Run on A:

```bash
openssl x509 -in /root/landing-hy2-ca.pem -noout -fingerprint -sha256
```

After confirming they match, enter `/root/landing-hy2-ca.pem` at A's certificate prompt. Never copy B's private key or disable TLS verification. If B uses another deployment tool, copy from its actual public certificate path.

Standard VLESS/HY2 and this project's native Shadowrocket Reality links are supported. A sing-box JSON containing exactly one proxy outbound also works, including embedded public trust material. Remote subscriptions and imported executable directives are not processed. A `pinSHA256` URI requires a matching certificate; insecure TLS options are rejected. Account quotas, expiry and usage remain independently managed on A. B's passwords/UUIDs are not included in client exports or personal subscriptions.

Controls include connection tests, global relay, direct restoration and deletion of saved landing credentials. **Landing failures do not automatically fall back to the entry VPS exit.** In selected-domain mode, unmatched traffic stays direct by choice. Explicit direct restoration exposes the entry VPS egress IP. Relay and WARP are alternative policies: selecting one replaces the other's active routing. This feature does not chain WARP or add a generic SOCKS5/HTTP upstream configuration.

Existing sing-box cores handle forwarding without an extra public proxy listener or relay daemon. Imports use field allowlists and refuse unknown routing changes and obvious loops back to managed listeners. Private routing state/backups hold landing credentials and embedded public trust material; existing update/restore/uninstall workflows manage them. Verify that DNS aliases, external forwarding or multiple VPS instances cannot create a loop.

**Speed depends on latency, loss and bandwidth on both links, both VPS CPUs and the residential connection's upload capacity.** Relay cannot remove landing bottlenecks. Compare real uploads/downloads and latency with direct access. The built-in check validates TCP/HTTPS reachability, not residential-IP classification, service unlocking, public UDP reachability or speed improvement. Both providers may count transferred traffic. Protocol fields follow [sing-box VLESS](https://sing-box.sagernet.org/configuration/outbound/vless/) and [sing-box Hysteria2](https://sing-box.sagernet.org/configuration/outbound/hysteria2/).

## HAProxy TCP passthrough (V2.7)

Open **d → 11 HAProxy TCP passthrough**, then **12 Usage guide**. Use this when A has a good client-facing route and B runs a TCP node, such as **VLESS + Reality + Vision** or an existing **Trojan** node. A can run only HAProxy; this mode does not require a sing-box node on A.

```text
Phone → A HAProxy TCP forwarder → B node → website
```

1. **Prepare B.** This manager can install Reality/Vision; an existing Trojan/TCP node from another tool also works. Keep B's egress direct to retain the residential IP and allow B's actual node TCP port from A.
2. **Add forwarding on A.** Open **d → 11 → 1**. Enter the name, A's listen IP and forwarding port, and B's IP/hostname and TCP node port. Defaults: A listens on `0.0.0.0:8443`; B uses port `443`. IPv6 listen `::` is IPv6-only. One rule per entry port, up to 16 rules; Enter accepts the default name.
3. **Type `y` to enable.** Busy ports, ports reserved by managed TCP nodes, obvious local loops and B's TCP reachability are checked. The configuration must pass `haproxy -c`. Failures leave previous configuration; restart failures restore previous files, activity and boot state. Changes briefly interrupt forwarded connections. Active UFW gets an allow rule for the new TCP port; configure provider firewalls separately.
4. **Edit B's node on the phone.** Copy B's node and change only the connection address to **A's public IP/hostname** and the connection port to **A's forwarding port**. Keep B's UUID/password, SNI, Reality public key/Short ID, fingerprint and certificate verification. A stores no node authentication/private key and needs no B CA file. For self-signed TLS on B, the phone must still securely trust B's certificate.
5. **Connect and check.** Shadowrocket uses the edited node; destinations should see B's exit IP. Authentication, per-user usage/quotas and expiry belong on **B**. HAProxy forwarding bypasses A's sing-box account service and cannot be charged against A's personal quotas.

This passes TCP bytes without terminating TLS, adding insecure TLS options or PROXY headers. **HY2/QUIC/raw UDP are unsupported**; protocol-carried UDP inside a TCP node depends on B/client support. Use the sing-box relay at **d → 10** for HY2. TCP reachability does not verify authentication, streaming access or speed improvements; test with the client. DNS targets are re-resolved: keep aliases from pointing back to any entry rule, and avoid cross-server forwarding loops. Use your own trusted B with authenticated nodes.

The independent service is `skybyte-haproxy.service`; files live under `/etc/singbox-v2/haproxy/`, with directory mode 700 and state/config mode 600. HAProxy is installed on demand from Ubuntu/Debian repositories with existing package configuration retained. First installation prevents the default service from starting automatically; an unenabled default service stays disabled. Existing external HAProxy services are not stopped or reconfigured. Workers use the distro `haproxy` account; the owned service restricts capabilities/filesystem access.

The submenu provides status, activity/boot controls, restart, TCP tests and rule removal. **2 Edit rule** replaces a landing/listener while keeping other rules; if B changes, update B's authentication/SNI on the phone as needed. **9 Backup, 10 Restore, 11 Uninstall**: existing rules are also automatically backed up before applying changes under `/etc/singbox-v2/haproxy-backups/`. Restore validates and replaces TCP rules, restoring saved activity/boot state. Full sing-box backups include a `haproxy` subdirectory; restore it separately through menu 10 after restoring sing-box, preserving current forwarding until explicitly requested. Full manager uninstall backs up and removes the owned relay; independent removal is available too. Keep the package, external `/etc/haproxy/haproxy.cfg`, other services, backups and firewall rules. Unknown files, modified units and symlinks cause refusal.

TCP forwarding and validation follow the [HAProxy TCP documentation](https://www.haproxy.com/documentation/haproxy-configuration-tutorials/protocol-support/tcp/) and [HAProxy 2.6 manual](https://docs.haproxy.org/2.6/configuration.html).

## FAQ

### Which VPS operating systems does SKYBYTE Manager support?

Ubuntu/Debian VPS instances using systemd. Official asset mappings cover amd64, arm64, armv7 and 386; management requires root. The automated test matrix covers Ubuntu 24.04 and Debian 11, 12 and 13 on amd64; validate other versions and architectures before deployment.

### Does Hysteria2 require a domain and a purchased certificate?

No. HY2 can generate a self-signed certificate for the public IP, but clients must establish certificate trust with TLS verification enabled. Domain deployments can use an existing certificate or ACME issuance. Personal HTTPS subscriptions require a domain and a trusted certificate.

### How do I import nodes into Shadowrocket, v2rayN or Clash Verge?

Menu **b → 2** exports client files, and **b → 4** displays Shadowrocket node QR codes. Retrieve files from `/etc/singbox-v2/` on your VPS over SSH/SFTP. Clash Verge Rev/Mihomo uses the complete YAML; OpenClash can merge the Mihomo fragment. Check protocol support in your client core. Enable personal online subscriptions separately through **b → 6**.

### Does WARP guarantee streaming or AI service access?

No. Routing supports direct-only, global WARP, or WARP for selected streaming and AI domains. Availability depends on the egress IP, platform policies and account. Streaming probes report the VPS egress response at the time of testing.

## Other VPS provider affiliate links

| Provider | Affiliate link |
| --- | --- |
| AkileCloud | [Visit AkileCloud](https://akile.ai/register?aff_code=0be67084-ae2e-4095-a586-2a3ee5c970f0) |

**Affiliate disclosure:** These links contain the author's referral identifiers. Purchases through them may earn the author a commission to support SKYBYTE Manager development and maintenance. Listings do not rank performance or promise streaming access; current pricing, availability and terms are determined by each provider.

[Subscribe to SKYBYTE on YouTube](https://www.youtube.com/@SKYBYTE9119) for script updates and VPS tutorials.
