# SKYBYTE Manager V2.1

A Bash-based Ubuntu/Debian VPS manager with Simplified Chinese and English interfaces.

YouTube: [SKYBYTE9119](https://www.youtube.com/@SKYBYTE9119) · [中文](README.md)

The main menu includes the SKYBYTE ASCII logo. Menus are bold green, credential links bold red, warnings bold yellow and errors bold red on ANSI terminals. Set `NO_COLOR=1` to disable colors. Every YES confirmation is case-insensitive.

## Installation

Requires root, Ubuntu/Debian, systemd and a public IPv4 address. Supports x86_64/arm64. The existing `install.sh` entry point remains available:

```bash
curl -fsSL https://raw.githubusercontent.com/skylink9119/sing-box-v2/main/install.sh -o install.sh
sudo bash install.sh
```

Until the development branch is merged, that command installs the main version. To test this branch, clone the repository, switch to the branch and run `sudo bash ./singbox-v2.sh`. Review downloaded scripts before execution.

The manager downloads an official stable sing-box binary and verifies its SHA-256 digest against GitHub Release metadata. It does not run a remote package installer. Choose a language at first launch; it is saved in `/etc/singbox-v2/language.conf`. Menu **6 → 1** changes language.

**Installation refuses to overwrite an existing configuration, manager state, sing-box binary, service or occupied protocol port.** Management and updates preserve UUIDs, passwords and server configuration. New deployments use TCP 443 / UDP 443. Configure the provider firewall separately.

## Menu and features

| Menu | Category | Functions |
| --- | --- | --- |
| 1 | Protocol installation and Argo tunnels | Reality / HY2 / dual; Quick / Named |
| 2 | Nodes and subscriptions | Information / exports / custom names |
| 3 | Services and logs | Controls / logs / Argo status |
| 4 | Server and network | Initialization / UFW / firewall / BBR / hopping / traffic / diagnostics |
| 5 | Updates and backups | Manual / weekly / backup / restore |
| 6 | Settings and uninstall | Language / privacy / uninstall |
| 0 | Exit | |

Initialization updates apt indexes, upgrades packages, installs administration tools and checks time synchronization, DNS, HTTPS, SSH and UFW. It preserves an active time-sync service and does not enable UFW, change SSH, configure BBR or reboot. Package upgrades may restart services; retain console access.

Before enabling UFW, the manager detects SSH ports from sshd listeners, `sshd -T` and `SSH_CONNECTION`, then asks you to verify the port. Detected ports and the verified port are allowed, together with deployed protocol ports and active HY2 hopping ranges. Menu 4 → 3 audits UDP 443 and range rules. Complex UFW rules require manual inspection; provider security groups cannot be inspected by this script.

vnStat reports **total VPS interface traffic**, never separate Reality/HY2 traffic. History starts when vnStat begins collecting data.

## HY2 and verified TLS

Installation accepts a node name prefix; press Enter for `SKYBYTE`. Existing deployments can use menu **2 → 3**. Exports append `-Reality` or `-HY2` to avoid duplicate protocol names. Names support up to 64 characters, including Chinese, spaces and ordinary symbols; URI fragments are percent-encoded. All client formats use the same names. Renaming preserves server configuration, UUIDs and passwords and does not restart the service. Node names, client headings, file paths and instructions use bold yellow on color terminals; links and configuration contents remain red.

Choose either:

- **No-domain self-signed certificate:** generates a certificate with the public IPv4 SAN, valid for 365 days. Clients must trust its public certificate.
- **Existing TLS certificate:** supply its domain, full certificate chain and private-key paths. Installation checks expiry, hostname/IP and key matching. The chain must also be trusted by clients. Supplied files are not modified.

Server and client passwords match; URI credentials are percent-encoded. Certificate verification stays enabled. Self-signed certificates are not trusted by default, so importing only a URI is insufficient.

Menu 2 → 2 exports:

| File | Purpose |
| --- | --- |
| `v2rayn-nodes.txt` / `v2rayn-subscription.txt` | v2rayN URIs / local Base64 subscription; verify core support and certificate trust |
| `shadowrocket-nodes.txt` / `shadowrocket-subscription.txt` | Shadowrocket URIs / local Base64 subscription content; no hosted URL is deployed |
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

Exports contain credentials, remain local under `/etc/singbox-v2/` and use mode 600 inside a mode-700 directory. No public HTTP subscription server is created. Never publish exports in repositories or issues. Restart the service after certificate renewal/replacement; after replacing a self-signed certificate, re-export and update client trust.

## Hopping, updates and restore

Node information is grouped into v2rayN, Clash Verge/Mihomo YAML, sing-box JSON and Shadowrocket subscription sections with dashed separators. The terminal displays actual URI, complete YAML/JSON or Base64 content plus file paths. Import full configurations as new local client profiles; existing client configurations are not overwritten. sing-box uses the first node by default; change `route.final` to another outbound tag when needed. Use Mihomo rather than classic Clash, which does not support these protocols. URI/Base64 formats remain compatible; no hosted subscription URL is deployed.

**No domain does not mean no certificate.** Default URIs retain `insecure=0`. Importing a URI does not establish self-signed certificate trust, and enabling TLS does not establish trust.

On iPhone, install `hy2-client-ca.mobileconfig`, then enable full trust under **Settings > General > About > Certificate Trust Settings**. Install only a certificate securely obtained from your own VPS via SSH/SFTP after verifying its fingerprint. This profile adds system root trust; remove it when no longer needed. It contains no node password or private key. Root profiles are not generated for leaf-only certificates, and existing server certificates are preserved. System trust does not prove Shadowrocket HY2 uses that trust store; verify with connection logs. Use a trusted CA certificate if unsupported. See [Apple certificate trust instructions](https://support.apple.com/en-us/102390).

Menu **4 → 9** checks config, service, actual UDP listener and certificate, and prints a read-only packet check command. A local listener does not prove provider/mobile-network UDP reachability. Use actual connections or URL tests in Shadowrocket; ICMP latency does not validate HY2.

Hopping is off by default. Ranges must be within 1024–65535 and contain at most 10001 ports. The manager owns only the `ip singbox_v2_hop` table, checks for collisions, persists IPv4 UDP redirects to 443 through systemd and permits the range in active UFW. sing-box/Mihomo exports include the range and a 30-second interval; basic URIs retain the base port. Allow the range in your provider firewall. Disabling hopping leaves UFW rules for manual cleanup to avoid deleting rules used by other applications.

Updates back up first, download and check a candidate binary, then replace the binary, restart and check service health. Startup failures restore the previous binary. Manual updates require confirmation; weekly updates are off by default and run on **Sunday at 04:00 in the server timezone**, with up to 15 minutes of randomized delay. Service health alone does not prove client connectivity.

New backups use separate `config/`, `state.json` and `sing-box.bin` paths, including snapshots of external TLS certificate/key files. Restore backs up the current deployment and attempts rollback on failure. It disables managed hopping and clears its state; re-enable hopping when required. Other nftables tables are untouched. The old broken directory/binary backup layout is not directly supported. Backups are not automatically pruned; protect disk space and private keys.

## Validation

Menu **6 → 3** requires case-insensitive `YES` confirmation and first backs up configuration, certificates and the binary. Backup failure cancels removal. It stops automatic updates, managed hopping and sing-box, then removes owned units, the binary, node configuration, generated certificates/exports and identifiable manager executable copies. Changed unit ownership/start paths or symlinked key files cause refusal. Successful uninstall exits the menu.

Backups, external certificates, unknown user files, reports, UFW allow rules, BBR/FQ settings and system packages such as vnStat remain. It does not reset the firewall or delete unrelated nftables tables. Backups contain private keys; protect permissions and disk space. To restore after uninstall, deploy again and restore the retained backup through menu 5 → 4.

```bash
bash -n install.sh singbox-v2.sh
shellcheck install.sh singbox-v2.sh
python3 -m unittest discover -s tests -v
```

Set `SING_BOX_BIN` and `MIHOMO_BIN` to include real engine validation: all three server modes, Mihomo YAML parsing, and local forwarding through HY2 with sing-box/Mihomo clients. Mihomo tests require PyYAML. Credentials and certificates are generated in temporary directories and are never committed.

GitHub Actions runs checks in Ubuntu 24.04 and Debian 12 containers. See [audit and testing notes](docs/TESTING.md). Local handshakes do not replace live VPS tests of provider firewalls, UDP NAT, systemd startup or Shadowrocket/v2rayN GUI imports. Validate these on a disposable VPS with snapshots and console access.

## Privacy, legal notice and references

For lawful networking education and server administration, subject to applicable law and service terms. Installation, updates and optional diagnostics contact third parties such as GitHub, api.ipify.org and ipinfo.io, which can see the source IP. No developer telemetry or credential uploads. Local diagnostic reports are pruned after 30 days. Provided as-is; back up before deployment.

- [sing-box HY2](https://sing-box.sagernet.org/configuration/outbound/hysteria2/)
- [sing-box TLS](https://sing-box.sagernet.org/configuration/shared/tls/)
- [Hysteria URI scheme](https://v2.hysteria.network/docs/developers/URI-Scheme/)
- [Mihomo TLS](https://wiki.metacubex.one/en/config/proxies/tls/)

## Argo Quick / Named Tunnels

Menu **1 → 4** adds a separate VLESS + WebSocket node to an existing managed Reality/HY2 deployment. The origin listens only on loopback; existing credentials and configuration are preserved. All client exports use verified HTTPS/WSS. Cloudflare terminates outer TLS and can inspect WebSocket payloads.

Quick mode needs no account/domain; restart changes the hostname, requiring refreshed imports. [Cloudflare documents Quick Tunnels as testing services without uptime guarantees](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/). Named mode requires a remotely managed tunnel and published hostname configured in your account: route HTTP to `http://127.0.0.1:8080` (use your selected local port), enable WebSocket support, and avoid interactive Access login. Enter hostname and Token locally; account DNS/routes are not provisioned by this script.

Controls include status/start/stop/restart/refresh/removal. Registration does not establish end-to-end reachability. Disconnected Quick nodes are omitted. Tokens use mode 600 and `--token-file`, are excluded from exports, and included in private backups. Removal preserves account tunnels/DNS. Restore re-registers before export. Official cloudflared downloads are SHA-256 verified.

Menu **2 → 4** displays one Shadowrocket node QR code per installed/exportable node, separated by dashed lines. Scan with Shadowrocket. The manager installs Ubuntu/Debian package `qrencode` when needed; links are encoded locally through stdin and no QR images are saved. Self-signed HY2 still requires certificate trust; keep QR codes private.

Shadowrocket native links are additionally saved in `shadowrocket-native-nodes.txt`, with a Base64 list in `shadowrocket-native-subscription.txt`. VLESS uses Base64 authority plus native remarks/peer/xtls parameters, following the [Xboard Shadowrocket exporter](https://github.com/cedar2025/Xboard/blob/master/app/Protocols/Shadowrocket.php). Menu 2 → 4 encodes these links. Standard files remain unchanged; HY2 keeps its existing verified-TLS URI. Native links have not been GUI-tested in Shadowrocket.
