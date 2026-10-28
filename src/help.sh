usage_help(){
 printf '%s' "$YELLOW"
 if [[ ${LANGUAGE_CHOICE:-zh_CN} == en_US ]];then cat <<'HELP_EN'
SKYBYTE Manager — quick guide
1. Install: main a → Reality/HY2/both. Enter defaults, allow actual TCP/UDP ports in provider firewall.
2. Node edits: main a → 5. Change admin ports/address/SNI or add/remove a protocol without resetting credentials/usage. Active hopping is disabled after edits; re-enable it for the current listener.
3. Client import: main b → 1 or 4. Use Shadowrocket native links/QR, v2rayN, full Mihomo YAML or sing-box JSON. Self-signed HY2 needs explicit public-certificate trust; never share private keys.
4. Accounts: main g. Initialize, create accounts and set quota/expiry. Share personal exports, not administrator nodes. Accounts are not actual people and may share credentials.
5. HTTPS subscriptions: obtain a trusted certificate through main e → 6, then main b → 6. Create/rotate/revoke personal links through user menu 16. Configure provider TCP access. Tokens grant access to credentials: keep links private. Revocation does not rotate node passwords.
6. Certificates: main e → 6 issues isolated ACME/Certbot certificates using HTTP-01 or Cloudflare DNS-01; auto-renew is opt-in. HTTP requires public TCP80. DNS tokens remain private. Existing websites/certificates are preserved.
7. WARP/media: main d → 9 / 8. WARP defaults to selected media/AI domains. It cannot guarantee location or unlocking. Anonymous tests do not verify playback. WARP menu 6 maintains catalogs; applying them is a separate confirmation.
8. Backup: main e → 2 creates a backup; 3 restores it; 7 lists/preflights/encrypts/imports or explicitly prunes old backups. Backups contain keys. Restore keeps current usage/policies and current subscription tokens.
9. Versions: main e → 1 selects this release's tested core, latest stable or a specific version/downgrade. Every managed config must validate; weekly auto-update remains removed.
10. Resources: main d → 7. Each account uses a core. Capacity depends on measured memory/CPU/traffic. Account quotas are periodically enforced, not byte-exact billing.
11. Residential landing / VPS relay: main d → 10, then 6 for step-by-step help. Import one Reality/Vision or HY2 landing URI/JSON. Clients connect to this VPS and destinations see the landing exit. Self-signed HY2 requires trusted public certificate material. Relay and WARP are alternative routing policies; failed relay traffic has no automatic direct fallback. Measure both links before judging speed.
12. HAProxy TCP passthrough: main d → 11, then 12 for help. A may run only the TCP forwarder; B runs the authenticated Reality/Trojan node. On the phone, keep B's credentials/SNI/TLS trust and change only the address/port to A. HY2/raw UDP are unsupported. User quotas belong on B. This menu has separate backup/restore/uninstall controls; full sing-box backups include a haproxy subdirectory for separate restoration.
13. Reality target checks: main d → 12. Check configured targets or a custom hostname/port/SNI; verify DNS, TCP, TLS 1.3, certificate and HTTP/2. Read-only, with bounded network timeouts; this does not test client-to-VPS connectivity.
14. Node parameters: main b → 7 shows UUID/public key/short ID/SNI. Important data is stored on this VPS: keep it private and install/enable a firewall through d → 2 after allowing SSH and node ports.
15. Installation checks: main a → 7. New installs and Reality additions run preflight checks; local binds do not prove public inbound access. The short HTTPS install entry is sky9119.cc/sb.sh.
CLI: --help, --self-check. Maintenance flags are used by owned systemd services.
HELP_EN
 else cat <<'HELP_ZH'
SKYBYTE Manager — 快速使用说明
1. 安装：主菜单 a 选择 Reality、HY2或双协议。回车使用默认值，云安全组需放行实际 TCP/UDP 端口。
2. 节点修改：主菜单a → 5，可改管理员端口、地址、SNI或增删协议，保留凭据与用量。修改后已启用的跳跃会关闭，请按当前监听端口重新开启。
3. 导入客户端：主菜单b → 1或4，提供小火箭专用链接/二维码、v2rayN、完整 Mihomo YAML与sing-box JSON。自签名 HY2 须信任公开证书；不要分享私钥。
4. 用户管理：主菜单g，初始化后添加用户并设额度/有效期。只分享个人节点，不要分享管理员节点；账户数量不代表真实人数，无法阻止凭据分享。
5. 在线订阅：主菜单e → 6获取可信证书，再通过主菜单b → 6配置HTTPS服务。用户菜单16签发、重置、撤销个人链接。云安全组需允许订阅 TCP 端口。Token可获取节点凭据，链接请保密；撤销订阅不等于更换节点密码。
6. 证书：主菜单e → 6，用隔离的 ACME/Certbot 目录通过 HTTP-01 或 Cloudflare DNS-01申请，自动续签需手动开启。HTTP须公网 TCP80可达，DNS Token私密保存，不停止已有网站、不覆盖外部证书。
7. WARP/流媒体：主菜单d → 9 / 8。WARP默认仅所选流媒体和AI域名，不能保证国家或解锁；匿名检测不验证播放。WARP菜单6维护规则列表，应用新列表需单独确认。
8. 备份：主菜单e → 2新建、3恢复、7列表/预检/加密导出/导入/确认清理旧备份。备份含私钥。恢复保留当前用量、策略和当前订阅Token。
9. 版本：主菜单e → 1选本版测试内核、最新稳定版或指定版本/降级，须检查全部托管配置。每周自动更新保持移除。
10. 资源：主菜单d → 7，每个用户一个内核，容量需实测。配额周期检查，不是精确计费。
11. 住宅落地 / VPS 中转：主菜单d → 10，再选6查看具体步骤，导入一个 Reality/Vision 或 HY2 落地链接/JSON。客户端连接本 VPS，网站看到落地出口。自签名 HY2 须提供可信公开证书；中转与 WARP 分流择一启用，中转失败不自动直连。速度需按两段链路实测。
12. HAProxy TCP 透传：主菜单d → 11，再选12查看说明。A 可只运行 TCP 转发，B 运行带认证的 Reality/Trojan 节点；手机保留 B 的认证、SNI及TLS验证，仅改连接地址和端口为 A。不支持 HY2/原生UDP。配额在 B 管理。本菜单可单独备份、恢复与卸载，完整 sing-box 备份中的 haproxy 子目录需单独恢复。
13. Reality 握手检测：主菜单 d → 12。检测当前目标或自定义域名/端口/SNI；检查 DNS、TCP、TLS 1.3、证书和 HTTP/2。只读且有网络超时，不代表客户端到 VPS 已连通。
14. 节点参数：主菜单 b → 7 查看 UUID、公钥、Short ID 和 SNI。重要数据保存在本 VPS，请做好保密；务必通过 d → 2 安装并启用防火墙，先放行 SSH 和实际节点端口。
15. 安装前检测：主菜单 a → 7；新装及追加 Reality 会自动检查。端口可绑定不等于公网入站连通；短安装入口为 sky9119.cc/sb.sh。
命令行：--help、--self-check。维护参数供本工具的 systemd 服务使用。
HELP_ZH
 fi
 printf '%s' "$RESET"
}
