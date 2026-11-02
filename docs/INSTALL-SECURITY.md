# 安装校验、最小依赖与账号资源

## 安装链

构建顺序为管理脚本 → install.sh → bootstrap.sh。install.sh 固定管理脚本的
SHA256；bootstrap.sh 固定 install.sh 的 SHA256。下载为空、语法不合法、哈希不符、
脚本与校验清单同时被替换时，均停止执行。安装入口保持版本固定。

这条链以最初获取的 bootstrap 为信任起点。HTTPS 和同一 Release 的 SHA256SUMS
不能独立抵御整个仓库被接管。已信任入口的固定哈希可拒绝后续文件被替换；
首次入口可额外使用 GitHub 构建证明核验。

`.github/workflows/attest.yml` 从发布标签重建，逐文件比较公开 Release 附件后，
为这些构建文件生成 GitHub/Sigstore 来源证明。CI actions 固定到 commit SHA。
证明不是代码无漏洞的保证，也不能替代对源仓库、工作流身份和源码提交的信任。

下载正式版文件后，可在具有 GitHub CLI 的管理电脑核验，再复制到 VPS：

```bash
gh attestation verify bootstrap.sh --repo skylink9119/sing-box-v2 --signer-workflow skylink9119/sing-box-v2/.github/workflows/attest.yml
```

也可以对 install.sh、singbox-v2.sh 和其余发布附件分别执行同一命令。
证明在 Release 发布后由工作流生成；工作流未通过时不要把该版本当作已通过来源验证。
GitHub 文档：https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations

## 非交互管理脚本安装

在 root 的 Ubuntu/Debian 上下载并验证 bootstrap 后：

```bash
bash bootstrap.sh --non-interactive
```

也可设置 `SKYBYTE_NON_INTERACTIVE=1`。此模式只安装经过校验的管理脚本，成功退出，
不读取菜单输入、不创建节点、不启用服务、防火墙或 BBR。安装完成会输出管理脚本绝对路径；
首次交互运行时再选择语言并注册 sb 快捷命令。它不是无人值守节点部署接口。
默认交互安装方式不变。未知参数或非法环境变量在下载前报错。

## 依赖包

普通安装入口只在缺少工具时补装 curl、CA 证书、Python 与 util-linux；
节点安装按协议准备必要依赖，QR、流量统计、证书、WARP 等功能按需安装。
vim/git/htop/mtr/traceroute 等原先属于用户主动选择的“新服务器初始化”，
并非普通节点安装的默认包。现在初始化也默认只装基础依赖，额外运维工具和系统升级
分别输入 y 才执行，并使用 --no-install-recommends。

## 多账号内存

受限账号为每个正在运行的账号启动一个 sing-box 进程，以独立端口、认证、流量总计
与生命周期执行配额。禁用、到期、用尽或计量失败的账号会停止。仅增加账本记录
不等于必然增加进程；实际开销取决于同时运行账号数、协议和连接负载。

运行账号数增加时，独立进程的私有内存确实增加，这是当前架构开销，尚未通过本次安装链
改动消除。RSS 相加包含共享页，Linux 上优先结合 PSS 和 MemAvailable 评估。
官方本项目验证的 1.14.3 构建未包含 V2Ray API；不能假设任意官方核心均支持按用户统计。
共享核心模式需要另行设计可靠计量、动态停用、故障隔离、迁移及真实协议回归，不能直接
拼接配置后声称保留独立配额。官方说明：https://sing-box.sagernet.org/configuration/experimental/v2ray-api/

菜单 d → 7 查看实际运行账号、进程 RSS、可读时的 PSS、有效可用内存和保留余量。
可见 cgroup v1/v2 限制会收紧预算。容量参考以当前最大账号 RSS × 2 为每个新增运行账号预算，
保留有效总内存 25%、至少 256 MiB，估算值不超过软件支持的 100 个总账号。
RSS 包括共享页，使用它作为预算偏保守；PSS 单独展示，不把 RSS 合计当作物理内存净消耗。
无运行账号、无法获取 MemAvailable 或限制组使用量时不猜测容量。该经验公式不是压测，
不会自动调整账号上限、配额或进程；高连接数和 HY2 缓冲等仍可能超过估算。

CI 的 account-benchmark 附件记录
10/30/50 个空闲账号的实测，包含可用时的 PSS。它只是该测试环境的容量快照，
不能用来保证 VPS 的最大用户数、流量吞吐或计费精度。
