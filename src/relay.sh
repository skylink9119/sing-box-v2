relay_verify(){
 local address
 address=$(warp_engine relay_probe "$1") || { err "$(L '落地节点连接验证失败；未应用中转。请检查地址、凭据、证书和中转到落地的链路。' 'Landing connection failed; relay not applied. Check address, credentials, trust and the entry-to-exit link.')";return 1; }
 ok "$(L '落地 TCP / HTTPS 出口验证通过：' 'Landing TCP / HTTPS egress verified: ')$address"
 say 'UDP 可达性和实际速度需另行实测；检测不代表住宅 IP 属性或平台解锁。' 'UDP reachability and speed need separate measurement; this test does not establish residential IP classification or platform access.'
}
relay_switch(){
 local mode=$1 profile=$2 domains=${3:-example.com} snap admin=false argo=false users=false
 check_owned && warp_guard && users_guard && argo_guard || return 1
 if [[ $mode != direct ]];then relay_verify "$profile" || return 1;fi
 snap=$(backup) || return 1
 if systemctl is-active --quiet sing-box.service;then admin=true;fi
 if [[ -f $BASE/argo-state.json ]] && systemctl is-active --quiet skybyte-argo-node.service;then argo=true;fi
 if [[ -f $BASE/users.json ]] && systemctl is-active --quiet skybyte-users.service;then users=true;users_stop || return 1;fi
 if ! warp_engine relay_switch "$mode" "$profile" "$domains";then warp_resume "$admin" "$argo" "$users" || :;return 1;fi
 if ! warp_resume "$admin" "$argo" "$users";then
  if [[ $users == true ]];then users_stop || :;fi
  warp_engine restore "$snap" || return 1
  warp_resume "$admin" "$argo" "$users" || :
  err "$(L '中转重启失败，已回滚原出站配置。' 'Relay restart failed; previous routing restored.')";return 1
 fi
 ok "$(L '中转出站模式已应用：' 'Relay routing applied: ')$mode"
 say "备份：$snap" "Backup: $snap"
}
relay_import_menu() (
 local choice source link trust stage mode domains rc=0
 stage=$(mktemp -d "$BASE/relay-import.XXXXXX") || return 1
 trap 'rm -rf -- "$stage"' EXIT
 prompt_options '1 粘贴节点链接（隐藏输入）  2 导入本地节点 / sing-box JSON 文件  0 返回' '1 Paste node URI (hidden input)  2 Local node / sing-box JSON file  0 Back'
 prompt_read '> ' choice || { rm -rf "$stage";return 0; }
 case $choice in
  1)
   prompt_read "$(L '落地 Reality/Vision 或 HY2 链接（隐藏）：' 'Landing Reality/Vision or HY2 URI (hidden): ')" link secret || { rm -rf "$stage";return 0; };echo
   printf '%s\n' "$link" > "$stage/source";unset link;source=$stage/source;;
  2) prompt_read "$(L '私密节点文件路径（仅一个落地节点）：' 'Private node file path (exactly one landing node): ')" source || { rm -rf "$stage";return 0; };;
  0) rm -rf "$stage";return 0;; *) rm -rf "$stage";return 1;;
 esac
 say 'HY2 自签名：从落地 VPS 经可信 SSH/SFTP 获取公开证书并核对指纹，不要提供私钥。受信任 CA 证书可回车跳过。' 'Self-signed HY2: retrieve the public certificate over trusted SSH/SFTP and verify its fingerprint. Never supply a private key. Press Enter for a trusted CA certificate.'
 prompt_read "$(L 'HY2 公开信任证书路径（可选）：' 'HY2 public trust certificate path (optional): ')" trust || { rm -rf "$stage";return 0; }
 if ! warp_engine relay_prepare "$source" "$stage/profile.json" "$trust";then rm -rf "$stage";return 1;fi
 prompt_options '1 全部节点流量走落地（默认）  2 仅指定域名走落地，其余直连  0 取消' '1 All node traffic through landing (default)  2 Selected domains; others direct  0 Cancel'
 prompt_read '> ' choice || { rm -rf "$stage";return 0; };choice=${choice:-1};domains=example.com
 case $choice in
  1) mode=global;;
  2) mode=restricted;prompt_read "$(L '域名后缀，空格分隔：' 'Domain suffixes, space-separated: ')" domains || { rm -rf "$stage";return 0; };;
  0) rm -rf "$stage";return 0;; *) rm -rf "$stage";return 1;;
 esac
 warn "$(L '此操作替换当前 WARP / 中转出站策略，并短暂重启运行中的管理员、用户和 Argo 节点。客户端仍连接本 VPS；落地凭据不会导出给用户。' 'This replaces current WARP / relay routing and briefly restarts active admin, account and Argo nodes. Clients still connect to this VPS; landing credentials are not exported.')"
 if confirm "$(L '验证落地并启用中转？' 'Verify the landing node and enable relay?')";then relay_switch "$mode" "$stage/profile.json" "$domains" || rc=$?;fi
 rm -rf "$stage";return "$rc"
)
relay_help(){
 printf '%s' "$YELLOW"
 if [[ ${LANGUAGE_CHOICE:-zh_CN} == en_US ]];then cat <<'RELAY_HELP_EN'
Residential landing / VPS relay — usage guide

Copy the residential server's node URI into the entry server's manager.

First identify the two servers:
  A: entry server. Your phone connects to A.
  B: residential IP server. B accesses websites; websites see B's residential exit IP.
Both servers need working nodes. Open a separate SSH terminal for each server.

1. Open B's terminal.
   Install Reality + Vision or HY2 if needed; an existing working node is fine.
   In SKYBYTE Manager, select 2 → 1 View nodes.
   Copy one complete red URI beginning with vless:// or hysteria2://.
2. Switch to A's terminal.
   Open 4 → 10 Residential landing / VPS relay.
   Select 1 Import / replace landing, then 1 Paste node URI.
3. Paste B's URI and press Enter.
   Hidden input displays no characters while pasting; this is expected.
4. Handle the certificate prompt.
   For Reality or HY2 with a trusted CA certificate, press Enter.
   For self-signed HY2 on B, copy B's PUBLIC certificate to A, verify its fingerprint
   and enter its file path on A. See the certificate commands below.
5. Choose 1 All node traffic through landing (Enter accepts the default), then type y.
   The script tests B's connection, backs up and applies the policy if successful.
   Relay is enabled when import completes.

Finally, Shadowrocket uses A's node URI or QR code.
Path after connecting: Shadowrocket → A entry server → B residential server → website.

Only for self-signed HY2 on B: public certificate transfer
  Run on A over trusted SSH/SFTP (replace LANDING_VPS_IP with B's address; SSH defaults to 22):
    scp root@LANDING_VPS_IP:/etc/singbox-v2/hy2-client-ca.pem /root/landing-hy2-ca.pem
  For another SSH port, add -P with that port to scp.
  Compare SHA256 fingerprints through a trusted channel:
    On B: openssl x509 -in /etc/singbox-v2/hy2-client-ca.pem -noout -fingerprint -sha256
    On A: openssl x509 -in /root/landing-hy2-ca.pem -noout -fingerprint -sha256
  After confirming they match, enter this path at A's certificate prompt:
    /root/landing-hy2-ca.pem
  Never copy B's private key or disable TLS verification.
  If B uses another deployment tool, copy from its actual public certificate path.

Preparation and checks:
  Keep B's egress direct to retain the residential exit; disable WARP routing on B if active.
  Allow B's actual node port from A: TCP for Reality, UDP for HY2, including the provider firewall.
  If A uses self-signed HY2, Shadowrocket still needs to trust A's public certificate.
  On A, select 2 Test landing: the reported egress should belong to B's residential connection.
  Test actual access, uploads/downloads and latency on the phone.

Controls: 1 import/replace; 2 test; 3 global relay; 4 restore A's direct exit;
          5 remove saved landing credentials after disabling relay or switching to WARP;
          6 this guide; 0 back.
Landing failure has no automatic direct fallback. Relay and WARP are alternative policies.
Selected-domain mode keeps unmatched traffic direct.
Speed depends on both links; the connection test does not prove a speed increase or residential IP classification.
RELAY_HELP_EN
 else cat <<'RELAY_HELP_ZH'
住宅落地 / VPS 中转 — 使用说明

把住宅服务器的节点链接，填进中转服务器的脚本里。手机连接中转服务器。

先分清两台机器：
  A：中转服务器，负责让你的手机连接。
  B：住宅 IP 服务器，负责访问网站，让网站看到住宅 IP。
两台服务器都要有可用节点。操作时，分别打开它们的 SSH 终端。

1. 打开 B 的终端。
   未安装节点时先安装 Reality + Vision 或 HY2；已有可用节点就直接使用。
   运行 SKYBYTE Manager，选择 2 → 1「查看节点」。
   复制红色的完整链接，例如以 vless:// 或 hysteria2:// 开头的一整条。
2. 切换到 A 的终端。
   进入 4 → 10「住宅落地 / VPS 中转」。
   选择 1「导入 / 更换落地节点」，再选择 1「粘贴节点链接」。
3. 把刚才 B 的链接粘贴进去，按回车。
   粘贴时屏幕不会显示字符，这是隐藏输入，正常。
4. 处理证书提示。
   B 使用 Reality 或受信任 CA 证书的 HY2，可以直接回车。
   B 使用 HY2 自签名证书，需要先把 B 的公开证书复制到 A，核对指纹，
   再填写它在 A 上的文件路径。具体命令见下方。
5. 选择 1「全部节点流量走落地」，回车使用默认值，再输入 y 确认。
   脚本验证 B 的连接成功后，备份并应用出站策略；导入完成时就会启用中转。

最后，小火箭使用 A 的节点链接或二维码。连接成功后的路线就是：
小火箭 → A 中转服务器 → B 住宅服务器 → 网站。

仅 B 使用 HY2 自签名时：公开证书复制方法
  在 A 通过可信 SSH/SFTP 执行（将住宅VPS_IP换成 B 的地址，默认 SSH 端口 22）：
    scp root@住宅VPS_IP:/etc/singbox-v2/hy2-client-ca.pem /root/landing-hy2-ca.pem
  SSH 端口改过时，在 scp 命令中加 -P 和实际端口。
  通过可信通道核对两端的 SHA256 指纹：
    B 上：openssl x509 -in /etc/singbox-v2/hy2-client-ca.pem -noout -fingerprint -sha256
    A 上：openssl x509 -in /root/landing-hy2-ca.pem -noout -fingerprint -sha256
  确认指纹一致后，在 A 的证书路径提示中填写：
    /root/landing-hy2-ca.pem
  只复制公开证书，不要复制 B 的私钥，也不要关闭 TLS 验证。
  B 使用其他工具部署时，按其实际公开证书路径复制。

准备与检查：
  为保留住宅 IP，B 的出站保持直连；若开启过 WARP，先切回直连。
  放行 A 到 B 的实际协议端口：Reality 使用 TCP，HY2 使用 UDP，云防火墙也需放行。
  如果 A 的入口也是 HY2 自签名，小火箭仍需信任 A 的公开证书。
  在 A 选择 2「测试落地连接」，显示的出口应属于 B 的实际住宅出口。
  再用手机测试实际访问、上传、下载和延迟。

按钮说明：1 导入 / 更换；2 测试连接；3 切回全局中转；4 恢复 A 的直连出口；
          5 先恢复直连或切换 WARP，再删除保存的落地凭据；6 本说明；0 返回。
落地失败不会自动改用 A 的出口；中转和 WARP 分流择一启用。
也可选择指定域名模式，未匹配流量按设置直连。
速度取决于两段链路，连接验证不能证明实际提速或住宅 IP 分类。
RELAY_HELP_ZH
 fi
 printf '%s' "$RESET"
}
relay_menu() (
 check_owned && warp_guard || return 1
 local choice stage rc=0
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 printf '%s' "$YELLOW";warp_engine relay_status "${LANGUAGE_CHOICE:-zh_CN}";printf '%s' "$RESET"
 say '路径：客户端 → 本 VPS → 落地 VPS → 网站。落地失败不自动改用本机出口。' 'Path: client → this VPS → landing VPS → destination. Landing failure does not automatically use this VPS as the exit.'
 prompt_options '1 导入 / 更换落地节点  2 测试落地连接  3 全局中转  4 恢复直连  5 删除已保存的落地凭据  6 使用说明  0 返回' '1 Import / replace landing  2 Test landing  3 Global relay  4 Restore direct  5 Remove saved landing credentials  6 Usage guide  0 Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
 if [[ $choice == 1 ]];then relay_import_menu;return $?;fi
 if [[ $choice == 6 ]];then relay_help;return 0;fi
 [[ $choice != 0 ]] || return 0
 stage=$(mktemp -d "$BASE/relay-action.XXXXXX") || return 1
 trap 'rm -rf -- "$stage"' EXIT
 if ! warp_engine relay_export "$stage/profile.json";then rm -rf "$stage";return 1;fi
 case $choice in
  2) relay_verify "$stage/profile.json" || rc=$?;;
  3) confirm "$(L '验证并切换所有节点到住宅落地出口？当前 WARP / 中转分流将被替换。' 'Verify and route all nodes through the landing exit? Current WARP / relay routing will be replaced.')" && relay_switch global "$stage/profile.json" || rc=$?;;
  4) confirm "$(L '恢复原始直连路由？网站将看到本 VPS 出口 IP。' 'Restore original direct routing? Destinations will see this VPS egress IP.')" && relay_switch direct "$stage/profile.json" || rc=$?;;
  5) confirm "$(L '删除保存的落地凭据？已启用中转时须先恢复直连或切换 WARP。' 'Remove saved landing credentials? First restore direct routing or switch to WARP if relay is active.')" && warp_engine relay_forget || rc=$?;;
  *) rc=1;;
 esac
 rm -rf "$stage";return "$rc"
)
