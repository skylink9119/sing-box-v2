# SKYBYTE Manager V2.3

基于 Bash 的 Ubuntu/Debian VPS 管理工具，提供简体中文和 English 界面。

YouTube：[SKYBYTE9119](https://www.youtube.com/@SKYBYTE9119) · [English](README_EN.md)

主菜单包含 SKYBYTE ASCII logo；菜单绿色加粗、节点链接红色加粗、警告黄色加粗、错误红色加粗。支持 ANSI 的交互终端显示颜色，`NO_COLOR=1` 可关闭。所有 `YES` 确认不区分大小写。

## 安装入口

需要 root、Ubuntu/Debian、systemd 和公网 IPv4；支持 x86_64/arm64。保留 `install.sh` 一键入口：

```bash
curl -fsSL https://raw.githubusercontent.com/skylink9119/sing-box-v2/main/install.sh -o install.sh
sudo bash install.sh
```

开发分支未合并时，上述命令仍安装 main 版本。测试当前分支可先克隆仓库并切换到对应分支，再运行 `sudo bash ./singbox-v2.sh`。建议先审阅下载的脚本。

脚本安装 sing-box 官方稳定版二进制，按 GitHub Release API 的 SHA-256 摘要检查下载，不执行远程软件包安装脚本。首次启动选择语言，保存于 `/etc/singbox-v2/language.conf`，菜单 **6 → 1** 切换语言。

**已有节点配置、状态、sing-box 二进制、服务或对应端口占用时，安装会拒绝覆盖。** 普通管理与更新不会重建 UUID、密码和配置。新协议部署使用 TCP 443 / UDP 443；云防火墙需另行设置。

## 菜单与功能

| 菜单 | 分类 | 功能 |
| --- | --- | --- |
| 1 | 协议安装与 Argo 隧道 | Reality / HY2 / 双协议；临时 / 固定隧道 |
| 2 | 节点与订阅 | 节点信息 / 订阅导出 / 自定义名称 / 小火箭二维码 / 用户管理 |
| 3 | 服务与日志 | 服务控制 / 日志 / Argo 状态 |
| 4 | 服务器与网络 | 初始化 / UFW / 防火墙 / BBR / 跳跃 / 流量 / 诊断 |
| 5 | 更新与备份 | 内核更新 / 每周内核更新 / 备份 / 恢复 / 管理脚本更新 / 证书管理 |
| 6 | 设置与卸载 | 语言 / 隐私声明 / 卸载 |
| 7 | 用户与配额 | 人数 / 用量 / 额度 / 有效期 / 故障诊断 / 资源 |
| 0 | 退出 | |

初始化更新 apt 索引、升级软件、安装常用工具，检查时间同步、DNS、HTTPS、SSH 和 UFW。保留已有运行中的时间同步服务；不自动开启 UFW、改变 SSH 端口、设置 BBR 或重启。系统升级可能重启相关服务，应保留 VPS 控制台。

开启 UFW 前，从 sshd 监听、`sshd -T` 和当前 `SSH_CONNECTION` 识别 SSH 端口，再要求人工核实；已识别端口与确认端口均会放行。同时按实际配置放行协议端口与已启用的 HY2 跳跃范围。菜单 4 → 3 检查 UDP 443 和跳跃范围规则；复杂 UFW 规则可能需要人工判断，无法读取云安全组。

vnStat 显示 **VPS 网卡总流量**，不能当作 Reality/HY2 各自流量；历史统计从 vnStat 开始采集时起算。

## HY2 与安全证书验证

安装时可输入节点名称前缀，直接回车默认 `SKYBYTE`；已有部署可使用菜单 **2 → 3** 修改。导出名称自动附加 `-Reality` 或 `-HY2`，例如 `香港线路-Reality`、`香港线路-HY2`，避免双协议重名。名称最多 64 个字符，支持中文、空格及常用符号；URI 名称会正确编码。名称在所有客户端格式中保持一致，修改名称不改服务端配置、UUID 或密码，也不重启服务。节点名称、客户端类型、文件路径和说明在支持颜色的终端中显示黄色加粗，链接和配置内容保持红色。

HY2 可以选择：

- **无域名自动自签名**：生成带公网 IPv4 SAN 的证书，默认有效期 365 天。客户端必须信任对应公开证书。
- **已有 TLS 证书**：输入证书域名、完整证书链和私钥路径。安装检查有效期、域名/IP 和私钥是否匹配；证书还须能在客户端建立可信证书链。不会改写提供的文件。

服务端密码与客户端密码保持一致，URI 对特殊字符进行编码。保持 TLS 验证开启；自签名证书不受客户端系统默认信任，单独复制 URI 不能解决信任问题。

菜单 2 → 2 导出：

| 文件 | 使用方式 |
| --- | --- |
| `v2rayn-nodes.txt` / `v2rayn-subscription.txt` | v2rayN 节点 URI / 本地 Base64 订阅，导入后核实客户端核心及证书信任 |
| `shadowrocket-nodes.txt` / `shadowrocket-subscription.txt` | 小火箭单节点 URI / 本地 Base64 订阅内容；不自动部署在线订阅 URL |
| `clash-verge.yaml` | Clash Verge Rev/Mihomo 完整本地配置，含代理组和路由；默认本地混合端口 7890 |
| `sing-box-client.json` | sing-box 完整客户端 JSON，默认本地混合端口 1080，路由使用首个节点 |
| `nodes.txt` / `subscription-base64.txt` | Shadowrocket、v2rayN 等支持相应协议的客户端；导入后核实 TLS 信任设置 |
| `mihomo-proxies.yaml` | Mihomo/OpenClash 配置片段，合并 `proxies` 及自签名所需的 `tls.custom-certifactes`（字段拼写为上游格式） |
| `outbounds.json` | 包含 `outbounds` 的 sing-box JSON 配置片段；合并到已有客户端配置 |
| `hy2-client-ca.pem` | 自签名部署的公开证书，供手动建立信任 |
| `hy2-client-ca.cer` / `hy2-client-ca.mobileconfig` | DER 公开证书 / iOS 信任描述文件；描述文件仅为 CA 证书生成，需手动安装并启用信任 |
| `subscription-notes.txt` | 信任说明、证书 SHA-256 指纹及跳跃提示 |

协议从实际 `config.json` 自动识别。自签名 sing-box JSON 内嵌公开证书；Mihomo YAML 内嵌信任证书并提供指纹，`skip-cert-verify: false`。HY2 URI 包含 `insecure=0` 和自签名证书指纹，但不同客户端是否支持 URI 指纹、私有 CA 和跳跃字段存在差异。

Shadowrocket/v2rayN 使用自签名证书时：通过可信 SSH/SFTP 通道取回 `hy2-client-ca.pem`，在服务器运行 `openssl x509 -in /etc/sing-box/hy2-selfsigned.crt -noout -fingerprint -sha256` 并通过可信通道核对指纹；按客户端/所用核心支持的方式导入信任证书，保持证书验证开启。无法配置可信 CA 的客户端应使用受信任 CA 签发的已有证书。**不要传输或导入服务端私钥。**

导出文件包含节点凭据，目录 700、文件 600，仅保存在 `/etc/singbox-v2/`，不部署公共 HTTP 订阅服务。不要上传公共仓库或粘贴进公开 issue。证书续期/替换后重启服务；自签名证书更换后重新导出并更新客户端信任。

## 端口跳跃、更新与恢复

节点信息按 v2rayN、Clash Verge/Mihomo YAML、sing-box JSON、小火箭订阅四块显示，并用虚线隔开。终端直接显示对应链接、完整 YAML/JSON 或 Base64 内容，并列出文件路径。客户端配置仅作为新的本地配置导入，不覆盖已有客户端配置；完整 sing-box JSON 默认使用首个节点，可修改 `route.final` 选择其他出站。经典 Clash 内核不支持这些协议，应使用 Mihomo。订阅文件仍保留原始 URI/Base64 格式，未部署在线订阅 URL。

**“无域名”不等于“无证书”。** 默认链接保留 `insecure=0`；只导入链接并不能建立自签名证书信任。TLS 开启也不表示信任已建立。

iPhone 可安装导出的 `hy2-client-ca.mobileconfig`，再进入 **设置 → 通用 → 关于本机 → 证书信任设置**，手动开启该证书的完全信任。只安装从自己 VPS 经可信 SSH/SFTP 通道取得、指纹一致的证书。描述文件增加系统根证书信任，停用后可删除；不包含节点密码或服务端私钥。已有证书不是 CA 时不会生成根证书描述文件，也不会替换已有服务端证书。系统信任能否被小火箭的 HY2 实现采用，需要用实际连接日志验证；不支持时使用受信任 CA 证书。参考 [Apple 手动信任证书说明](https://support.apple.com/en-us/102390)。

菜单 **4 → 9** 检查配置、服务、实际 UDP 监听和证书，并提供只读抓包命令。本机 UDP 正常监听不能证明云防火墙或手机网络已放行 UDP。小火箭应测试实际连接或 URL，普通 ICMP 延迟不能验证 HY2。

HY2 跳跃默认关闭，范围限制为 1024–65535、最多 10001 个端口，只操作 `ip singbox_v2_hop` 专属表。开启时检查现有表冲突，使用 systemd 持久化 IPv4 UDP 转发到 443，并放行已启用的 UFW。sing-box/Mihomo 导出包含跳跃范围与 30 秒间隔，普通 URI 保留基本端口；云防火墙仍需放行范围。关闭后不擅自删除可能被其他应用使用的 UFW 规则，必要时人工清理。

更新先备份，再下载并检查候选二进制，配置检查通过后替换、重启并检查服务状态；启动失败恢复旧二进制。手动更新需要确认，每周自动更新默认关闭，时间为**服务器时区周日 04:00**，最多随机延迟 15 分钟。服务状态不等于端到端可达。

新备份使用 `config/`、`state.json`、`sing-box.bin` 独立路径，包含已有外部证书/私钥的快照。恢复前备份当前配置，失败尝试回滚。恢复后关闭托管跳跃并更新状态，需要时重新开启；不会替换其他 nftables 表。旧版目录/二进制同名备份格式不能直接恢复。备份不自动删除，请保护磁盘空间和私钥。

## 测试与范围

菜单 **6 → 3** 卸载前要求输入 `YES`（不区分大小写），自动备份配置、证书和二进制，备份失败则取消。停止自动更新、托管跳跃及 sing-box 服务，再删除对应服务文件、托管二进制、节点配置、生成证书与订阅文件，以及可识别的管理脚本副本。服务标记或启动路径被修改、关键文件为符号链接时拒绝卸载。卸载成功后退出菜单。

保留备份、外部证书、未知用户文件、报告、UFW 放行规则、BBR/FQ 设置及 vnStat 等系统软件；不会重置防火墙或删除其他 nftables 表。备份仍包含私钥，请保护其权限和磁盘空间。需要恢复时先重新部署，再从菜单 5 → 4 恢复保留的备份。

```bash
for file in install.sh singbox-v2.sh src/*.sh; do bash -n "$file"; done
shellcheck install.sh singbox-v2.sh
python3 -m unittest discover -s tests -v
```

设置 `SING_BOX_BIN`、`MIHOMO_BIN` 后，测试包含实际 sing-box 三种服务端配置检查、Mihomo YAML 检查，以及 sing-box/Mihomo 客户端连接 HY2 服务端的本地转发。Mihomo 测试需要 PyYAML。凭据与证书在临时目录运行时生成，不提交仓库。

GitHub Actions 在 Ubuntu 24.04 和 Debian 12 容器执行检查。详见 [审计与测试记录](docs/TESTING.md)。本地握手不能代替真实 VPS 的云防火墙、UDP NAT、systemd 启动和 Shadowrocket/v2rayN 图形客户端导入测试；这些项目须在有快照和控制台的 VPS 上验证。

## 隐私、法律与参考

仅供合法网络技术学习和服务器管理，遵守当地法律及服务条款。安装、更新和可选诊断会访问 GitHub、api.ipify.org、ipinfo.io 等第三方，第三方可看到来源 IP；无开发者遥测，不上传节点凭据。报告本地保存，30 天后清理。软件按现状提供，部署前备份。

- [sing-box HY2](https://sing-box.sagernet.org/configuration/outbound/hysteria2/)
- [sing-box TLS](https://sing-box.sagernet.org/configuration/shared/tls/)
- [Hysteria URI 格式](https://v2.hysteria.network/docs/developers/URI-Scheme/)
- [Mihomo TLS](https://wiki.metacubex.one/en/config/proxies/tls/)

## Argo 临时 / 固定隧道

菜单 **1 → 4** 在已有本工具管理的 Reality/HY2 部署上增加独立 VLESS + WebSocket 节点，源站仅监听本机回环地址，保留已有凭据和配置。各客户端导出使用 HTTPS/WSS 并开启证书验证。Cloudflare 终止外层 TLS，可检查 WebSocket 载荷。

临时模式无需账号和域名，重启后地址变化，需要刷新并重新导入。[Cloudflare 将临时隧道定位为测试用途，不保证可用性](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。固定模式需要先在账号中创建远程管理隧道及公开主机名：HTTP 服务指向 `http://127.0.0.1:8080`（以实际选择端口为准），启用 WebSocket，避免交互式 Access 登录。本地输入主机名和 Token；脚本不自动配置账号 DNS 或路由。

支持状态、启动、停止、重启、刷新和卸载。注册成功不代表端到端可用；断开时不导出旧临时地址。Token 权限为 600，通过 `--token-file` 使用，不进入客户端导出，私密备份包含 Token。卸载保留账号隧道和 DNS，恢复后重新注册再导出。cloudflared 官方下载通过 SHA-256 校验。

菜单 **2 → 4** 显示小火箭节点二维码，每个已安装且可导出的节点单独生成，用虚线分隔。使用小火箭扫码导入；缺少工具时安装 Ubuntu/Debian 的 `qrencode` 软件包。链接通过标准输入在本机编码，不保存二维码图片。HY2 自签名仍需配置信任证书，二维码请勿公开。

新增小火箭专用链接文件 `shadowrocket-native-nodes.txt` 及 Base64 列表 `shadowrocket-native-subscription.txt`。VLESS 使用 Base64 地址和 remarks/peer/xtls 参数，参考 [Xboard 小火箭导出实现](https://github.com/cedar2025/Xboard/blob/master/app/Protocols/Shadowrocket.php)。菜单 2 → 4 使用专用链接生成二维码。原有标准文件保留，HY2 沿用开启验证的链接；专用格式尚未进行小火箭图形客户端实测。

进入交互菜单及切换语言后显示绿色加粗的版本和系统概览：操作系统、内核、架构、虚拟化、网卡 IPv4/IPv6，以及服务安装/运行状态。启动不查询第三方归属地；公网出口和归属地使用 IP 信息菜单查询。可选探测命令缺失不影响打开菜单。

## 用户数量、流量与有效期

入口 **主菜单 7**（原 **2 → 5** 仍保留）。先初始化用户管理（默认最多 10 个账户，可设 1–100），再添加用户，填写用户名、上传与下载合计额度（GiB）和有效天数。支持查看每人上传/下载/总用量、修改额度及有效期、启用/禁用、删除、重置累计用量，以及查看个人节点和小火箭二维码。到期或超额后停止该用户的节点及现有连接；续期不自动重置用量，重置需要单独确认。

人数上限实际限制未删除的账户数量，禁用和到期账户仍计入；不能识别真实人数或阻止同一账户分享凭据。修改额度保留原有效期，修改有效期保留额度和累计用量。有效期从创建/修改有效期时起计算，状态中以 UTC 显示。额度没有默认周期重置；`1 GiB = 1024³ 字节`。

本功能支持新建受限账户的 **Reality + Vision、HY2 或双协议**，沿用已安装主节点的协议组合。每人独立 UUID/密码、独立 sing-box 进程和随机可用端口，出口仍是同一 VPS。双协议的上传与下载合计计入该账户的额度。原有管理员节点配置和凭据保留，**不受用户上限、配额或有效期限制**；Argo 暂不支持受限账户。因此，请只向受限用户分发其个人节点，不要分发管理员节点。

个人计量使用该用户独立实例的 [Clash API](https://sing-box.sagernet.org/configuration/experimental/clash-api/) 累计流量；不使用 vnStat，也不把 VPS 总流量冒充个人流量。每个统计 API 仅监听 `127.0.0.1`，使用独立鉴权密钥。已有管理员主服务与用户服务独立启停，完整卸载会停止全部托管服务。

限制按周期检查（通常约 1 秒，账户较多或系统繁忙时延长），不是逐字节硬限额；超出量取决于传输速度和检查延迟。已采样用量原子保存并跨重启累计，最后一次采样之后的流量在异常断电、强制终止或关闭瞬间可能无法计入。统计接口不可用、计数异常或子进程意外退出时停用对应用户，修复后需显式启用；用户数据损坏时关闭受限节点。适合自用额度管理，不是精确计费系统。每个用户进程额外占用内存、CPU 和端口，请按 VPS 容量设置账户上限。

个人导出保存在 `/etc/singbox-v2/users/<用户ID>/`，支持原有客户端格式和小火箭二维码。仅分享所需的**客户端导出**；`server.json`、`state.json`、`private.key`、`users.json` 和备份包含私密数据，不能分享。文件权限为 600，目录为 700，不自动开启在线订阅服务。

启用中的 UFW 会放行对应用户节点端口；之后开启 UFW 也会加入已存在用户的规则。云防火墙需自行放行实际 TCP/UDP 节点端口，不要公开统计 API。端口分配避开已启用的 HY2 跳跃范围，开启新跳跃范围时拒绝覆盖用户 HY2 端口；用户节点本身不使用主节点的端口跳跃。删除用户或卸载不会擅自清除 UFW 规则。

配置备份包括用户策略、用量、独立配置及证书。恢复时保留当前仍存在的用户及其最新策略/累计用量，避免旧备份重置额度或复活已删除账户；暂停状态也保留。没有用户数据的旧备份不会删除当前用户。更新前检查全部用户配置，更新后重启此前运行的用户服务。systemd 用户主管服务为 `skybyte-users.service`；个人错误日志位于对应用户目录 `core.log`，只保留当前运行期间的有限日志。

## 管理脚本更新、证书与诊断（V2.3）

- **5 → 1** 更新 sing-box 内核；**5 → 5** 检查与更新 SKYBYTE Manager 管理脚本。两者独立。脚本更新读取 GitHub 最新正式 Release，对照发布资产的 SHA256，检查 Bash 与内嵌 Python 语法、版本，再原子替换托管脚本副本。已有配置、凭据和用量保留；脚本备份位于 `/etc/singbox-v2/manager-backups/`。此前运行的用户服务及 Argo 隧道会短暂重启，失败时恢复旧脚本。更新完成会进入新版菜单。开发版不自动降级。
- **主菜单 7** 直接进入用户管理，主菜单显示未删除账户数/上限、就绪账户数和主管服务状态。**用户菜单 4** 只修改流量额度；**13** 只修改从现在起的有效天数，操作后显示 UTC 到期时间。两项都不清空累计用量。
- **用户菜单 14** 显示安全的故障分类、时间、退出码、配置检查和本地日志路径；不输出 API 密钥和原始日志。认证失败、超时、无效响应、计数异常或进程退出都会停止对应账户。修复后选择启用用户；启用前重新验证配置和控制接口配置。账户过期/超额仍须修改相应策略，不能通过启用绕过限制。
- **4 → 10** 或 **用户菜单 15** 显示 sing-box / 用户进程数、RSS 内存、系统可用内存和负载。RSS 含共享内存，不能按快照保证最大用户容量；不存在固定的每人内存承诺。
- 启动时显示 HY2 证书剩余天数，30 天内到期或过期时提示。**5 → 6** 可检查有效期、续签后同步证书到个人节点并重载此前运行的服务、启停每日检查。域名/私钥不匹配或证书过期时拒绝重载。
- 每日检查**默认关闭**；开启后由 `skybyte-certificate.timer` 执行，并将结果写入 systemd 日志。它不会申请/续签证书；已配置的域名证书有效更新后才自动同步重载。续签工具也可设置部署钩子：`/bin/bash /usr/local/sbin/singbox-v2 --certificate-reload`。首次检查建立指纹基线；如在建立基线前已经续签，请手动同步重载一次。自签名证书改变只提示，须手动重载并重新核实客户端信任，始终保留 TLS 验证。

## 源码模块与构建

维护源码在 `src/`：`manager.sh` 为基础服务及安装逻辑，`subscriptions.sh` 为订阅导出，`users.sh` 为用户界面/服务，`users.py` 为配额与诊断，`operations.sh` 为更新/证书/资源，`menu.sh` 为主菜单及启动入口。运行 `python3 scripts/build.py` 生成完整 `singbox-v2.sh`；`python3 scripts/build.py --check` 检查是否同步。不要直接修改生成文件。

安装仍只需 `install.sh`，部署的脚本自带所有模块，不在运行时下载或加载额外文件。`bash singbox-v2.sh --self-check` 无需 root，可检查内嵌 Python 语法并输出版本。systemd/UFW 操作使用隔离模拟测试；实际 VPS 部署仍需验证。
