# PR #2：离线回归与 GitHub Actions

这是叠加 PR：`codex/ci-offline-tests-pr2` → `codex/security-hardening-pr1`。
起点为 `502fa974dbde9d3cae3ae7592b453b40a52a5f7d`。不自动合并 PR #1/#2。
PR #1 合并后先核实提交关系，再由维护者决定调整目标到 main，不能直接绕过安全加固基线。

## 运行入口

在 Python 3.12.14 的全新虚拟环境中安装：

```bash
python -m pip install --index-url https://pypi.org/simple --require-hashes --only-binary=:all: -r requirements-ci-build.lock
python -m pip install --index-url https://pypi.org/simple --require-hashes --no-build-isolation -r requirements-ci.lock
python -m pip check
python scripts/run_offline_tests.py
python scripts/run_offline_tests.py --harness
python scripts/verify_e_module.py
```

单独运行：`--suite security`（66 项）、`--suite business`（29 项）、
`--suite isolation`（16 项）；正常合计 111 项，跳过或零测试同样返回失败。
`--order reverse` 或 `--order shuffle` 检查顺序独立性；shuffle 使用固定种子。
独立 API 冒烟另有 26 项业务/授权断言，不把缺少索引和缺少 LLM 凭据当作成功。

前端使用 Node 24.19.0：

```bash
node scripts/check_frontend_artifact.test.mjs
node scripts/frontend_ci.mjs --output /tmp/new-scholaros-dist
python tests/browser_security_smoke.py --dist /tmp/new-scholaros-dist
```

输出目录必须尚不存在且位于仓库之外；不删除或覆盖既有产物。
浏览器只需 `requirements-browser.lock` 中的 websockets 与已安装 Chromium/Google Chrome。
浏览器检查启动回环 Mock fixture，不部署应用后端，不连接真实校园服务。

## 统一隔离

`tests/support.py` 在第一次应用导入前屏蔽 dotenv 加载，之后为每个测试创建：

- 新临时根目录、明确的合成环境、全部数据路径、上传临时目录、SQLite 与日志位置。
- 新 A/B/C/D 适配器，重置任务/资料/LLM 客户端缓存，防止执行顺序或旧索引带来假阳性。
- 合法 localhost Host 与合成 Bearer，匿名客户端另行创建；不降低后端鉴权。
- Python audit tripwire：阻断真实配置/课程数据读取、仓库外写入、非临时 SQLite、外部 DNS、
  未登记 socket 和非预期子进程。只有合成 TLS 测试登记的回环端口可连接。
- 吞掉 I/O 异常也会在测试退出时失败。只有 tripwire 自身的明确负向测试可以确认并消耗预期违规。

该机制是防止误操作的测试护栏，不是恶意原生代码的操作系统沙箱。
测试进程内不并发执行独立 test case；被测代码自身的线程仍在同一护栏内。
正常退出/异常路径清理临时目录；操作系统强制杀进程可能留下合成临时文件。
当前 CI 只运行 Linux，Windows ACL、dir_fd 行为未验证。

语义向量和 ASR 不属于当前离线目标：CI 不安装 torch/sentence-transformers，
隔离环境也显式使可选模型模块不可用，避免开发机上的模型缓存改变结果或触发下载。
关键词索引是真实构建和检索，没有伪造嵌入结果。

## 业务覆盖与最小修复

| 领域 | 实际覆盖 |
|---|---|
| 课程 | 实际课程遍历/任务映射，正常/空/缺少 ID/缺少名称、学期请求参数、重复课程、变化响应结构 |
| 作业 | 列表、HTML 详情富化、附件去重、未交/已交/已批改、缺少日期、非法日期/时区、ISO 秒与偏移、固定时钟的学期过滤 |
| 同步/存储 | 真 SQLite 去重与游标、相同名称不同 ID、重复批次计数、状态更新、原子写失败、输出前失败、输出后游标提交失败、重试、部分渠道失败及错误日志 |
| 附件元数据 | 正常/缺失/不可信链接、重复 URL、同名不同 URL、文件名冲突分配；不执行真实下载 |

新增业务测试首次有 7 项失败，定位后仅作以下生产修复：

1. `main.py` 跳过重复课程 ID；邮件游标不再提前推进。
2. 同步先原子 upsert JSONL，再记录指纹和游标，失败后单写者可以幂等重放。
3. `src/pipeline.py` 以不同 raw ID 计数；保留较丰富内容时也更新最新已知 status/completed/ddl；
   JSONL 使用现有私有原子写入器，避免固定 `.tmp` 路径与不完整覆盖。
4. `src/parsers/learn_html.py` 正确解析 ISO 时间偏移/秒，拒绝非法 ISO 时区。
5. `scripts/export_attachments.py` 同一批次相同记录/URL 只形成一个候选，不放松任何 URL/TLS/代理限制。

这不是完整跨文件/数据库事务或多写者队列：并发独立同步进程仍需后续设计。
仅保证已覆盖的单写者失败/重放行为。None 不会清除旧的已知工作流字段。
跨多次导出的附件版本识别仍未实现：manifest 的已有键是 raw ID+名称；
本次只验证同一批中不同 URL 和磁盘文件名冲突，不把它宣传为跨运行的版本管理。
独立课程实体 CRUD、真实同步、真实 SSO/MFA、代理下载兼容性、复杂文档沙箱均未新增。

## 既有脚本的副作用分类

- `verify_e_module.py`：已正式改为隔离入口，保留原 11 个接口并增强内容/状态断言；新增匿名与合成实流水线检查。
- `tests/review_legacy_smoke.py`：旧兼容入口转调正式入口。原 Host/无令牌负向断言继续存在于安全测试，
  不再要求已修复的主入口故意失败。
- `run_harness.py`：由统一隔离包装调用，源码扫描排除实际 `.env*`，保留模板检查和全部 13 项规则。
- `verify_e2e.py`、`verify_data_pipeline.py`、`verify_knowledge.py` 及 probe/full_pipeline 等仍是人工诊断工具，
  可能读取本地状态、请求 LLM 或写索引。常规 CI 禁止执行；policy 检查也拒绝将其加入步骤。

## CI 与供应链

工作流名称为 **ScholarOS Offline CI**，两个 job：`python`、`frontend`。
触发 push main/PR2 分支、普通 pull_request，另预留 workflow_dispatch。
没有 pull_request_target、Secrets、部署、Release 或签名配置。
权限只有 `contents: read`，checkout 不保留凭据；两个 job 各有 15 分钟超时。
无共享缓存、无跨 job 产物输入、无产物上传，因此没有未受信 PR 污染正式构建缓存的通道。
正常测试失败直接传播退出码，没有 continue-on-error 或 `|| true`。

官方 Action 固定提交通过 `git ls-remote` 和对应 `action.yml` 实际核实，均使用 Node 24 action runtime：

| Action | 已核实标签 | 完整 Commit |
|---|---|---|
| actions/checkout | v6.1.0 | d23441a48e516b6c34aea4fa41551a30e30af803 |
| actions/setup-python | v6.3.0 | ece7cb06caefa5fff74198d8649806c4678c61a1 |
| actions/setup-node | v6.5.0 | 249970729cb0ef3589644e2896645e5dc5ba9c38 |

Python 3.12.14 在官方 python-versions manifest 中确认，Node 24.19.0 在官方发行 SHA 文件中确认。
Python 直接测试依赖来自已测试环境；所有解析后的依赖及发行哈希写入 `.lock`。
主应用 `requirements.txt` 和前端锁文件未批量升级。测试组排除了重型可选模型依赖。
jieba 只有 sdist，因此先按哈希安装 setuptools 78.1.0/wheel 0.45.1，再以 `--no-build-isolation`
安装经哈希验证的源码包，避免构建时悄悄下载未锁定工具。构建执行已审查的 jieba setup，不代表源码包天然无风险。
锁文件由 uv 0.12.23 从可信 PyPI/TLS 生成；CI 使用 pip，不依赖 uv。
更新时分别运行 `uv pip compile <对应.in> --generate-hashes --python-version 3.12 --index-url https://pypi.org/simple --no-emit-index-url -o <对应.lock>` 并重新审查/验证。

前端 `npm ci --ignore-scripts` 使用现有 integrity 锁；审查发现的安装脚本属于 Darwin 可选 fsevents，
Linux 构建无需执行。干净构建已验证禁用脚本仍可工作。
构建只复制 Git 跟踪前端输入，拒绝被跟踪的环境文件、依赖目录、输出目录和源符号链接；
使用空 npm 用户/全局配置、全新缓存和最小子进程环境，避免读取本机 npm 认证或 Vite 环境文件。
实际校验 HTML 引用、所有资源存在、大小、路径/扩展名、符号链接、合成 canary 与 SHA-256。
这不能替代对已提交源码的秘密扫描；构建过程也不是恶意代码沙箱。CI 不提供真实凭据。

## 本地验证与云端证据

已在全新 Python 虚拟环境和全新 npm 构建目录执行：111 项 Python、9 项前端请求、7 项产物检查、
13 项 harness、26 项 API 冒烟、6 项 Chromium 场景；另检查语法、类型、Vite、YAML 和 diff。
固定随机顺序的 111 项回归也通过。原有 66 项安全断言保留。
本机 Chromium 为 154.0.8037.57；GitHub Ubuntu 24.04 镜像文档提供 Chrome/Chromium，
实际运行版本由浏览器检查输出记录，不假装浏览器镜像版本永久不变。

工作流实际经 actionlint 1.7.7 校验。工具从官方发行下载，归档 SHA-256 与官方列表一致：
`023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757`。
运行命令 `actionlint -shellcheck= .github/workflows/ci.yml`；未安装额外 shellcheck，不将其算作已执行。

负向控制：`python scripts/run_offline_tests.py --self-test-failure` 实际执行 1 个合成失败，退出 1。
该模式不进入正常 CI，也不修改正式断言或分支；证明的是本地 runner 传播失败，不能冒充云端 job 已红。
另有不安全工作流/秘密产物/缺失资源的负向断言。

GitHub Actions 的运行 ID、对应 SHA、job 状态必须在推送后通过真实页面核实，见本次交付报告。
首次真实运行为 [41604925965](https://github.com/Zhaoty24-git/ScholarOS/actions/runs/41604925965)，
对应 `08713e56c526d027e429fc96d70f54274a5cb393`：Python job 成功，frontend job 在浏览器步骤失败，
整体确实标为 Failure。公开页面只提供退出码，详细日志需要登录，公开日志路由返回 404。
没有将其算作通过或跳过失败步骤。后续兼容修正明确使用 runner 官方提供的稳定 Google Chrome
（其 Chromium 来自开发快照），使用可信 CDP 输入并等待 React 渲染，增加有界 CDP 等待与阶段注解，
便于在公开页面诊断后续失败。无法从首次公开信息断言具体根因已经确认。
修正后的本地六场景继续通过。第二次真实运行
[41606129082](https://github.com/Zhaoty24-git/ScholarOS/actions/runs/41606129082)
对应 `b1068350d55fc2b3acc74479479af0dab90667c5`，整体 **Success**（50 秒）：
Python job `125816276081` 成功（46 秒），frontend job `125816276645` 成功（31 秒），
两个 job 均未跳过。公开页面可核实 job 状态；详细日志仍要求登录，未声称读取了完整云端输出。
该运行同时覆盖前端构建、类型检查、六个浏览器场景及完整 Python 离线流程；
本段证据补录后的最终提交/运行以交付报告为准。
本地通过不等于云端 CI 通过。如果 Fork 禁用 Actions，只需维护者在 GitHub 的 Actions 页面启用工作流；
没有运行记录时，可在启用后创建本叠加 PR 触发 pull_request，或让 Codex 再提交正常变更触发 push。
新工作流尚未进入默认分支时，不承诺 workflow_dispatch 网页按钮已可用。
无需提供任何校园密码、API Key 或新的写入令牌，也不应修改仓库安全策略来绕过限制。

## 下一任务（仅规划）

PR #3 先评估 React/Vite + Capacitor，分离不经过后端令牌门的独立离线 demo 入口，
内置明确标识的合成课程、作业、通知列表/详情和导航，不依赖 Python 启动。
独立增加 Android Debug APK 工作流，提供实际 APK、构建 SHA、SHA-256 和手机下载/安装/飞行模式验收。
不嵌入校园账号/Cookie/LLM Key，不创建正式签名密钥；不能把离线 demo 宣称为真实校园同步。
本 PR 不创建 Android 工程、APK、Release 或部署服务。
