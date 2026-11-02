# 一个项目管理 sing-box 与 XHTTP

从 `sb` 进入 **a → 10**。XHTTP 是传输方式，节点使用 VLESS + XHTTP + Reality 或 TLS；不添加 Vision flow。
首次部署才查询并下载 [XTLS 官方最新稳定 Xray](https://github.com/XTLS/Xray-core/releases/latest)，校验 Release API SHA256 后使用。未部署 XHTTP 时不会下载、启动 Xray，也不会在打开菜单时联网查版本。

| 选择 | 功能与默认参数 |
|---|---|
| 1 | XHTTP + Reality 自动向导：名称、BBR/UFW/二维码选择、最终 y；TCP 443、自动公网地址、addons.mozilla.org:443、随机路径、auto 模式 |
| 2 | XHTTP + TLS/CDN 自动向导：先收集证书域名、可信 fullchain 与匹配私钥文件、CDN 选择，再收集配套选项并确认；TCP 2053、随机路径；CDN 默认 packet-up，直连 auto |
| 3 / 4 / 5 | 节点链接与 Xray 客户端 JSON / 保密参数 / 本机二维码 |
| 6 | 服务启停、日志及配置检查；操作后留在子菜单 |
| 7 | 名称、地址、端口、路径、证书修改与协议删除；保留 UUID/密钥；失败回退 |
| 8 | 查询最新稳定 Xray，再确认更新；检查配置，失败恢复原核心；现有核心不会在打开菜单时自动替换 |
| 9 / 10 | 独立 XHTTP 私密备份 / 恢复；备份包含凭据、私钥与证书 |
| 11 | 备份并卸载 XHTTP/Xray，保留 sing-box、未知文件和防火墙规则 |
| 12 | 手动指定端口、连接地址、监听地址族、握手目标、路径和模式 |

主菜单 **b → 1 / b → 7** 同时查看两类节点/参数。新安装也可只装 XHTTP，不必先装 sing-box。

自动模式的域名证书必须已经准备好，并使用真实文件绝对路径；请先在证书签发平台完成验证。CDN 域名/DNS、受支持的 HTTPS 端口和回源 TLS 验证仍需在提供商处配置。已有本项目 ACME 证书可使用其真实证书/私钥文件。
自动部署确认后不会再追问参数；无法取得公网地址、官方版本或检测失败时停止。TCP 443 被已有 Reality 占用时，不强行覆盖、不默认改成 8443，请用 12 选择空闲端口；HY2 UDP 443 与 XHTTP TCP 443 可以共存。

BBR/UFW/二维码复用公共配套模块。UFW 启用前先确认实际 SSH 监听、放行两种内核的节点端口；未知规则或其它公开监听需人工核对，不清空规则。云安全组须单独放行。IPv6 直连需客户端具备 IPv6。

## 数据、服务与兼容范围

- sing-box 原有路径与 `sing-box.service` 保持原样。
- XHTTP 配置/凭据/导出：`/etc/singbox-v2/xhttp`；核心：`/etc/singbox-v2/xhttp-core/xray`；服务：`skybyte-sb-xhttp.service`。
- 安装、编辑、更新和卸载共用 sing-box 管理锁；等待菜单输入时释放锁。检查停止服务所预留的 TCP 端口，避免双内核抢占端口。
- XHTTP URI、二维码、`client-xhttp-*.json` 和独立 Base64 导出供支持 XHTTP 的客户端使用。现有 sing-box JSON、Mihomo YAML、用户配额、个人 HTTPS 订阅与 WARP 设置仍针对 sing-box，未将 XHTTP 填进不兼容格式或声称共享计量。
- sing-box 完整备份附带 `xhttp.tar.gz`，独立恢复用 a → 10 → 10；sing-box 恢复不会悄悄改写 XHTTP。完整卸载会备份并移除本项目管理的两类节点；XHTTP 单独卸载不会删除 sing-box。
- 不自动接管已有独立 Xray 项目、`/etc/skybyte-xray` 或 `skybyte-xray.service`；它们的配置、密钥和服务均不覆盖。旧项目如占用端口，需先备份并人工停用或选择其它空闲端口。
- 参数、链接、二维码和备份均留在 VPS；不要公开。请安装并开启防火墙，先放行 SSH 与实际端口。

## 模块结构

| 模块 | 职责 |
|---|---|
| `modules/xhttp.sh` | 统一入口、隔离命名空间、子菜单适配 |
| `modules/xhttp_wizard.sh` / `xhttp_automatic.sh` | 前置选择与确认后自动部署 |
| `modules/xhttp_install.sh` / `xhttp_reality.sh` | 手动安装与握手网站选择 |
| `modules/xhttp_configuration.sh` / `xhttp_subscription.sh` | 参数编辑、链接与二维码 |
| `modules/xhttp_service.sh` / `xhttp_backup.sh` | 服务、事务回滚、内核更新与备份恢复 |
| `src/xhttp_core_*.py` | 路径归属、参数校验、配置/导出、原子事务、官方下载等后端模块 |
| `src/xhttp_backend.py` | 构建生成的可测试后端；修改上面的源模块后重新构建 |
| `tests/test_xhttp_*.py` | 双内核冲突、自动部署、取消/失败回退、真实内核连接等回归 |

后端及部分前端从作者的 SKYBYTE Xray Manager v0.1.34（源提交 `23d07f845b9759b1121f8558d9fe982c2a98d387`）复用，保留 GPL-3.0-only 版权声明。现在源码随 sing-box 项目维护、构建；运行时不访问第二个项目下载管理代码。共享诊断、APT、BBR、防火墙和菜单控制来自公共模块。
