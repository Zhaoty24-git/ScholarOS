# PR 1：单用户本地安全边界

本次保留 MIT LICENSE、原作者版权和提交历史。目标为本地单用户开发，
不是面向公网、多用户或移动端部署的完整认证方案。

## 启动与前端

1. 安装现有 `requirements.txt` 和前端锁文件依赖，无新增第三方依赖。
2. 使用安全随机源生成至少 32 字符的访问令牌，通过进程环境安全配置
   `SCHOLAROS_API_TOKEN`。支持 32–256 个 ASCII 字母、数字、`_`、`-`；
   不使用校园密码或 LLM Key 作为访问令牌，不将令牌放入 URL、Git 或日志。
   例如由 `secrets.token_urlsafe(32)` 生成，通过安全设置传入。
3. 从仓库根目录执行 `npm --prefix frontend ci`、`npm --prefix frontend run build`。
   新构建位于被忽略的 `frontend/dist/`，后端 `/app/` 只挂载此目录。
   必须在启动后端前构建；旧的 `frontend_static/` 不再被服务，以免提供不支持鉴权的旧 UI。
   旧云环境保存的外部 `--outDir` 构建命令需要调整后才能用于新的启动流程；本 PR 不修改环境设置。
4. 运行 `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`。
5. 在页面输入访问令牌。令牌只存在 JS 内存中；刷新或点击“锁定会话”后重新输入。
   GET、JSON POST、multipart 上传都使用 `Authorization: Bearer …`。
   设置页面只提交用户实际修改的字段，保留未修改的私有配置。

不要使用远程主机地址或 `0.0.0.0` 将服务暴露到网络。本阶段不提供远程 TLS、
用户管理、角色分离、令牌吊销服务或反向代理部署方案。所有持有令牌者拥有同一 owner 权限。
更换进程环境中的令牌并重启可撤销旧令牌。页面 XSS、本机恶意进程、浏览器扩展仍可能获取令牌。

## 访问控制与兼容性变化

- `/api/health` 公开且仅返回 `status=ok`；其余 `/api/`、OpenAPI 和文档入口均需令牌。
  未配置有效令牌返回 503；未授权返回 401，不接受 Cookie 或查询参数中的令牌。
- Host 仅允许 `localhost`、`127.0.0.1`；Origin 精确允许这两个主机的 8000 和 5173 HTTP 端口。
  开发模式 Vite 5173 可连接本地后端。其他端口、远程域名与反向代理需要另行设计，不能使用通配符放行。
- CORS 只约束浏览器读响应，不代替身份认证。Bearer 鉴权确认 owner 身份/权限；
  Origin 和 Fetch Metadata 检查、拒绝 Cookie 自动认证共同防止浏览器跨站触发操作。
  合法 Origin 的请求同样必须携带令牌；无 Origin 的 CLI 请求也必须鉴权。
- 设置状态仅返回“是否配置”，不再回传用户名、Key 片段、端点或 EXTRA_JSON 内容。
  API 不返回命令、内部路径字段、stdout/stderr 或原始诊断日志；解析异常只给出安全错误。
  绝对资料引用展示为文件名。API 数据包含用户自己的课程正文，应只供授权 owner 使用。
- JSON 校验错误不回显输入；未处理的业务异常在路由边界转成通用错误，不让异常正文进入服务器 traceback。
  API 使用 `no-store`；页面附带 CSP、nosniff、禁止外部嵌入和不发送 Referer 的响应头。
- 全部请求体上限 21 MiB（包含 multipart 开销）；单个上传文件 20 MiB。
  读取上传文件使用有界块。最多两个同时执行的写请求，超出返回 429。
  此限制按进程生效，不限制已返回 queued 的后台子进程总数。
- 原有页面中指向附件/资料文件、分块预览的部分路由在基线后端即不存在。
  本 PR 不补齐这些业务接口，也不把令牌塞进下载 URL；后续新增文件接口必须使用带鉴权的 fetch/Blob 下载。

## 配置、会话与认证

- 拒绝配置值中的 CR、LF、NUL；使用 dotenv 引号编码和字面值加载，避免注入及变量插值。
  同进程读改写加锁，去除被更新键的重复定义。`.env`、新保存的会话/信任文件和解析报告
  使用同目录临时文件原子替换，POSIX 权限 0600，拒绝目标符号链接。
  不批量改动用户已有私有文件；不承诺 Windows ACL 或多进程文件锁保护。
  已有多行 dotenv 值会阻断 API 写入，需 owner 先手动审查转换，避免遗留续行变成独立配置。
- 默认不读取账号文本文件。只有管理员显式设置 `SCHOLAROS_ALLOW_CREDENTIAL_IMPORT=1`
  后，已鉴权的 bootstrap 请求才可导入。默认值为禁用；不建议启用，不自动删除旧文件。
- 新保存的 Learn 会话保留 Cookie 域/路径并标为 Secure，拒绝不带作用域的旧字典格式。
  旧会话需要重新认证；本 PR 不自动迁移真实 Cookie。JWCH 恢复 Cookie 使用 Secure 标记，
  Info Cookie 导入仅允许精确 Info 域，拒绝扩大到父域。
- 下载的 SM2 helper 只有匹配 `SCHOLAROS_SM2_SHA256` 才允许执行。管理员必须先独立审查 helper，
  再配置其 UTF-8 文本 SHA-256；不提供默认摘要、不自动接受新版本、不允许绕过校验。
  Node 子进程只继承 PATH，不继承服务令牌或其他凭据环境变量，密码仍经 stdin 传递。
- 拒绝无 SM2 公钥时的原密码回退。认证表单和 SM2 脚本限 HTTPS 的
  `id.tsinghua.edu.cn`、`auth.cic.tsinghua.edu.cn`；拒绝 GET 方式的 Learn 凭据提交，
  密码表单 POST 禁用自动重定向，遇到重定向失败并要求单独审查。

**真实登录为阻断性待办：**Learn/JWCH 表单、重定向、短信/企业微信 MFA、信任设备与 Cookie 兼容性
均未进行真实验证。证据位置为 `LearnAdapter._login_with_password/_prepare_password`、
`JwchAdapter._login_with_password/_prepare_password` 和两个 `probe_*_double_auth.py`。
探测脚本的 OTP/信任设备流程及完整 SSO 跳转仍需单独审查，不能因为合成测试通过就投入真实账号使用。
固定摘要限制了远程代码变更，但 Node 执行本身不是操作系统沙箱。

## 附件和报告

- 学堂附件仅允许固定 HTTPS 主机 `learn.tsinghua.edu.cn` 的 443 端口。
  拒绝用户信息、非 HTTPS、私有地址解析和所有 HTTP 重定向，绝不向重定向目标转发会话或 XSRF。
  无需外部 CDN 放行。若真实学堂改用 CDN，需要单独审查来源和凭据隔离。
- 下载强制 TLS 校验、5 秒连接/15 秒读取超时、120 秒流式处理总预算和 50 MiB 大小上限。
  `Content-Length` 与实际流式字节均检查；失败清理临时文件，异常不带 URL/凭据正文。
  超时总预算在块间检查，可能额外等待一次读取超时。
- 使用安全文件名和目录内临时文件；以不覆盖已有路径的方式发布文件，避免遍历及符号链接覆盖。
  响应的 Content-Disposition 不再决定本地路径。邮件附件落盘也采用独占创建并检查解码后大小。
  IMAP 原始邮件仍是整体获取，尚无协议级预取大小限制；需另行处理。
- 删除了此前已跟踪的 `storage/material_parse_report.json`，保留其已有忽略规则并增加回归检查。
  新报告以 0600 写入但仍含本地诊断元数据，仅供本机 owner 使用，不应分享。
  **历史提交中的报告仍然存在**。如需审查历史敏感信息，应由 owner 私下检查；若确有凭据暴露，
  先撤销凭据，再单独审批历史清理及协作者同步方案。本 PR 不重写历史或强制推送。

## 离线验证与剩余边界

运行 `python -m unittest discover -s tests -p 'test_security.py' -v`。
测试在导入应用前禁用真实 dotenv 加载，使用合成环境、临时目录、Mock HTTP 响应，
禁止 Requests 真实外连。没有调用校园登录、外部 LLM 或下载语义模型。
另外运行 `python scripts/run_harness.py` 和 `npm --prefix frontend run build`。
前端请求 helper 回归运行 `npm --prefix frontend run test:security`，验证 JSON/上传请求头和锁定清除。
旧 `verify_e_module.py` 未携带令牌，不能再作为未修改的验收入口；下一任务应统一适配隔离测试配置。

剩余问题包括：恶意 PDF/Office/OCR 的 CPU/内存隔离、后台任务队列和进程总预算、
IMAP 原始邮件大小、真实 SSO 兼容性、完整日志/历史数据治理，以及远程部署身份/TLS。
当前上传大小/并发限制不能代替解析器沙箱；不要处理不可信的大型复杂文档。
本阶段不更改 Actions、不创建 Android 工程、不部署后端、不创建 Release。
