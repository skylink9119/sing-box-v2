# 专业检测方案与验证记录（2026-10-29）

## 选型结论

没有工具能保证所有平台/地区始终准确。按检测范围、专门接口、代理支持、维护路径与接入成本选择：流媒体使用 UnlockTests；线路/测速使用 goecs 的独立选项，不把完整硬件压力测评塞进日常菜单。

| 项目 | 核对结果 | 用途与选择 |
| --- | --- | --- |
| spiritLHLS/MediaUnlock_test | 提供的仓库返回 404 | 不作为安装来源，也不沿用“更新最快”的描述 |
| lmc999/RegionRestrictionCheck | 可访问，AGPL-3.0，支持代理和区域，仓库最近推送 2025-12-08 | 可独立复核；未把它的代码复制进项目 |
| spiritLHLS/ecs | README 指向 oneclickvirt/ecs；Shell 版主要维护，Go 版继续功能开发 | 使用官方推荐的 Go 路线 |
| oneclickvirt/UnlockTests | Apache-2.0，近期推送 2026-10-26；支持 JSON、区域、平台和 SOCKS5 | 替换旧页面分类器；全球与 AI 默认，另选全地区 |
| NextTrace | GPL-3.0，专门的路由追踪工具 | 本身不是流媒体引擎；本次线路入口使用 goecs 的三网回程/NT3 模块 |
| backtrace | MIT，仓库最近推送 2025-06-10 | 可单独复核，非本次默认集成 |
| HyperSpeed | 旧的 i-abc/Speedtest 仓库已归档 | 不以旧测速脚本作为默认入口；采用 goecs 的速度模块 |

最近推送时间只用于核对维护状态，不是准确度排名。来源：[UnlockTests](https://github.com/oneclickvirt/UnlockTests)、[融合怪 Go](https://github.com/oneclickvirt/ecs)、[融合怪 Shell 迁移说明](https://github.com/spiritLHLS/ecs)、[RegionRestrictionCheck](https://github.com/lmc999/RegionRestrictionCheck)、[NextTrace](https://github.com/nxtrace/NTrace-core)、[backtrace](https://github.com/zhanghanyun/backtrace)、[旧 Speedtest](https://github.com/i-abc/Speedtest)。

## 集成行为

- 打开菜单不联网、不下载、不检测；选择操作才查询官方 Release 和下载对应架构资源。
- 强制 HTTPS，校验官方 SHA256 和资源地址；每次运行重新校验缓存，保持当前一个资源，不通过安装脚本/管道执行远程 Shell。
- 流媒体默认 global + AI（区域 0,21），可选全地区；原生/DNS/代理类型、地区及未知/超时等状态保留上游判定，HTTP 200 不被本项目转换成“解锁”。
- WARP 操作先核实仅本机监听与实际 WARP 出口；显式 SOCKS5，无代理失败改走直连的回退逻辑。物理出口地址族和系统 DNS 辅助判定需区分，不能把 VPS 检测等同于手机实际分流。
- 三网回程仅开 backtrace/NT3；测速仅开 speed；综合网络检测开基础、流媒体、安全信息、回程与测速。全部关闭 CPU/内存/磁盘压力、上传、自动日志。测速与综合检测先确认流量消耗。
- 子程序使用临时 HOME/工作目录和清除代理等环境变量后的环境；不传节点配置、UUID、密钥或订阅；控制并发和执行时限，超时/中断清理进程组。
- 流媒体报告为权限 600 的本机 JSON，记录官方来源、发布标签、资源 SHA256、路径、结果与未完成原因。第三方探测仍会访问平台、DNS、路由/IP 服务，服务方能看到出口 IP。

## 验证与限制

已验证官方 macOS arm64 UnlockTests 和 goecs 发布资源摘要及实际 CLI 参数，不运行开发机器的公网带宽或硬件压力测试。用真实 UnlockTests、仅本机 SOCKS5 拒绝连接的服务器验证代理请求路径和失败结果：代理被访问，失败未被判定为解锁。官方 goecs 的 route/speed/full 所用全部参数经过实际 `-h` 解析，无未知参数。

新增隔离回归覆盖资源摘要、下载地址、缓存篡改、预览/重复资源、架构、ZIP 安全读取、符号链接、代理参数、环境隔离、真实子程序/JSON 解析、未知状态、部分结果、终端控制字符、上传与压力模块关闭、超时清理和菜单取消测速。旧页面解析器的专属测试已替换，原 WARP 路由和真实代理协议测试保留。

不能据此保证所有 VPS 的网络可达、流媒体播放/账户资格或 IP 原生属性；三网结果是当次到探测目标的路径，不代表所有客户端。综合测评语言强制中文以启用上游中国回程模块。
