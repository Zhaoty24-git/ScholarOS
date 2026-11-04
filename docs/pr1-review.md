# PR #1 复查与合并前验收

复查目标为 `Zhaoty24-git/ScholarOS` 的既有 PR #1，分支 `codex/security-hardening-pr1`，
复查起点 `2b9773ce9bffbe4ccb73e94ae10999aa49295080`，基线 `21795a4574ca98277a673c38e8887848a99f5b3a`。
没有新建 PR、修改 main、重写历史、改变网络策略或部署后端。

## 状态证据与限制

公开 PR 网页的结构化数据确认 PR #1 为 DRAFT、目标 main、未关闭/未合并；
Git 的 `refs/pull/1/head` 与开发分支相同。检查时公开 checks 页明确显示该提交没有检查。
会话页显示 No reviews，但部分动态模块加载失败；不能据此保证没有未显示的审查线程或平台权限要求。
没有使用受限的 GitHub API，也没有将 API 不可用解释为 PR 不存在。
main 仍为基线，是开发分支祖先，Git 层面没有需要解决的合并冲突；
这不替代 GitHub 的分支保护、最终 mergeability 和 required checks 决策。

## 发现、严重程度和修复

| 问题 | 程度 | 修复与证据 |
|---|---|---|
| DNS 预检查与 Requests 实际连接重新解析分离 | 中高，目标地址限制缺口 | 固定已验证数字 IP 的 HTTPS 池，保留域名 SNI/Host/证书校验。原 TLS 校验并未被证明可绕过；不声称已发生凭据窃取。代理无法约束时安全拒绝。`src/attachment_security.py`；Mock socket 与真实本地合成 TLS 测试 |
| 未鉴权未知 POST/健康路径可占写槽位；读体无总预算 | 中，可用性 | 所有不安全方法先鉴权；30 秒读体总超时；重复/非法/不匹配长度拒绝；断开、取消、异常释放。`backend/app/security.py`；直接 ASGI 副作用断言 |
| 锁定后旧请求仍返回、后端撤销后页面不锁定、旧业务工作可借新令牌 | 中，会话边界 | AbortController、会话版本、绑定会话的业务客户端、失效通知。`frontend/src/api.ts`、`App.tsx`；Node 竞态及 Chromium 场景 |
| 精确允许的 localhost 开发 Origin 被 blanket cross-site 判断误拒绝 | 中，功能回归 | 允许明确受信 Origin 但不免除鉴权；未知 Origin/跨站仍拒绝；授权前后均断言 |
| 外层鉴权拒绝缺少受信 Origin 的 CORS 响应头，开发前端无法读取 401 并锁定 | 中，会话/兼容性 | 仅为精确允许的 Origin 添加拒绝响应 CORS 头和 Vary，不对未知 Origin 放行 |
| splitlines 破坏合法 Unicode 分隔符；保留旧的引号/export-tab 键；裁剪有效密码空格 | 中，配置完整性 | 使用现有 dotenv parser 的绑定边界编辑、保留未改内容和合法空格，去除全部被更新键。临时配置的读写回归 |
| MFA 探测脚本仍自动跟随携带 OTP 的重定向；本地事务没有恢复期限 | 中高，凭据传输边界 | 固定主机、禁止 POST 重定向；10 分钟事务期限；日志只输出结果布尔值。`src/security.py` 和两个探测脚本；仅测试拒绝与进程边界，不冒充真实登录成功 |

新增测试先复现了 5 处后端失败、3 处前端失败，以及独立的开发 Origin 403 回归。
原有断言没有被删除或跳过；下载测试将 Mock 从 Session.get 移到新的适配器发送边界，
保留大小、重定向、路径、清理和 TLS 断言，并增加真实本地 TLS 测试。

## 实际验证结果

环境：Linux、Python 3.12、Node 24，现有依赖；本地 TLS 测试还使用 OpenSSL，浏览器测试使用已安装 Chromium。
没有增加第三方依赖、读取真实 .env、访问校园/LLM、使用真实凭据或下载模型。

| 检查 | 命令 | 数量 / 通过 / 失败 / 跳过 | 退出码 |
|---|---|---|---|
| 原 Python 基线重跑 | `python -m unittest discover -s tests -p 'test_security.py' -v` | 49 / 49 / 0 / 0 | 0 |
| 最终 Python 安全回归 | `python -m unittest discover -s tests -p 'test_*.py' -v` | 66 / 66 / 0 / 0 | 0 |
| 前端请求与竞态 | `npm --prefix frontend run test:security` | 9 / 9 / 0 / 0，原为 2 项 | 0 |
| 架构 harness | `python scripts/run_harness.py` | 13 / 13 / 0 / 0 | 0 |
| Python 静态语法 | `python -m compileall -q backend src scripts tests main.py` | 全部目标完成，无测试计数 | 0 |
| TypeScript | `frontend/node_modules/.bin/tsc --project frontend/tsconfig.json --noEmit` | 类型检查完成 | 0 |
| Vite | `npm --prefix frontend run build` | 生产构建完成 | 0 |
| Chromium 合成页面 | `python tests/browser_security_smoke.py` | 6 / 6 / 0 / 0 个功能场景 | 0 |
| 旧冒烟脚本复查 | `python tests/review_legacy_smoke.py` | 原脚本首项 Host 400，子运行退出 1；仅修正 Host 后 401；适配 Host/Token 后 11 / 11 / 0 / 0 | 包装验收 0，保留原失败记录 |
| 补丁卫生 | `git diff --check` | 无空白错误 | 0 |

Python 增加 17 项独立复查测试，覆盖连接池/真实 TLS、超时取消、长度、配置语法、MFA 边界等。
旧冒烟的 HTTP 200 包括缺少 LLM 配置的 blocked 响应，额外断言了 blocked，不声称问答成功。
Chromium 验证初始锁定不发 API、错误令牌、合法授权、锁定清空、刷新再授权、后端拒绝后重锁。
页面只连接本地合成服务，不代表真实业务数据、文件预览、校园同步或 AI 已验收。
原 49 项继续保留；Windows ACL/Windows 运行、真实代理连接、真实 SSO/MFA 和复杂资料解析没有执行。
测试 runner 有 httpx/Starlette 弃用提示，未为消除提示而升级依赖。

## 合并判断与剩余阻断

**修复后可以合并，当前仍建议保留 Draft。** 本次可独立验证的代码缺陷已修复，
但若本 PR 的合并验收包含当前云环境的实际附件下载和真实校园认证，则仍有明确功能阻断：

1. 当前继承代理不能提供可验证的 IP 绑定下载路径，本实现安全拒绝。需要兼容且可验证的代理传输方案，不能通过关闭代理来“修复”。
2. SSO/MFA、重定向、信任设备兼容性未验收。缺少独立审查的 SM2 pin 时继续阻断；
   本次禁止真实登录，不能补上这些实际验证，也不能把固定摘要视为 JS 沙箱。

这些限制需要独立的传输/认证验收安排。若将 PR 明确限定为安全默认拒绝的本地开发基线，
可以由维护者另行接受上述功能限制，但本报告不代替该决定，也不自动改 Ready 或合并。
其他剩余边界：解析器 CPU/内存沙箱、后台任务/多进程总预算、IMAP 原始邮件大小、
业务正文/元数据的完整隐私模式、历史报告治理，以及 Windows ACL；不能声称所有安全风险均已解决。

## 后续两个独立任务（仅规划）

### PR #2：隔离自动化与 GitHub Actions

- 抽取统一临时根目录、合成环境、无外网 fixtures，避免现有测试之间重复导入配置。
- 正式适配旧冒烟入口；增加解析、去重、增量游标和失败恢复的业务断言。
- CI 分别运行 Python、前端、类型和构建检查；Linux 必跑，Windows 文件行为单列。
- 最小 `contents: read`，固定 Action 提交及工具版本，设置超时；Fork PR 不使用真实秘密。
- 验收：全新环境可复现测试计数和退出码，故意破坏关键断言可使 CI 失败，产物不含配置或个人资料。

### PR #3：Android 离线测试版

- 评估现有 React/Vite 的 Capacitor 适配，先分离离线 demo 路由/数据与后端令牌锁定入口。
- 创建 Android 工程，支持课程、通知、作业列表及详情和基本导航；无 Python 后端也能启动。
- Debug APK 工作流独立审查；不创建正式签名密钥，不内置账号、Cookie 或 LLM Key。
- 验收：真实 APK、构建 Commit SHA 与 SHA-256 可下载；真机完成安装、冷启动、飞行模式浏览和详情返回验证。
- 离线 demo 必须明确标识，不能宣称真实校园同步已可用。

本次没有创建上述工作流、Android 工程、APK 或新 PR；完成复查后停止。
