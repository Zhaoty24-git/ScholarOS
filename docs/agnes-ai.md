# PR #4：Android Agnes AI 助手

基线为 PR #3 `68391c458e5db861c0b7737a05f5a8073222b968`。
分支 `codex/agnes-ai-pr4`，Base `codex/android-offline-apk-pr3`；不自动合并。
APK `com.scholaros.app` 保持稳定，versionCode 2，versionName `0.2.0-dev`。

## 已确认的接口与区域

用户已核对其国内站账号并提供当前官方文档及参数：

- 国内站（默认）：https://www.agnes-ai.cn/zh-Hans/docs/agnes-30-flash
  Base URL `https://api.agnes-ai.cn/v1`。
- 国际站（手动可选）：https://agnes-ai.com/zh-Hans/docs/agnes-30-flash
  Base URL `https://apihub.agnes-ai.com/v1`。
- 模型 `agnes-3.0-flash`；POST `<Base URL>/chat/completions`。
- JSON 的 model/messages，Authorization: Bearer，Content-Type: application/json。

云环境读取上述 API 域名根页面时均被代理拒绝，未绕过或更改策略；当前文档内容依据
用户提供并确认的官方摘录，不能声称本环境独立抓取了完整网页或已连通真实 API。
不读取账号、不索取密钥；真实服务验收只由用户在手机上输入新 Key 后进行。
原生 URL 只拼一次 `/v1`，不自动跨站重试。更换区域必须重新配置对应区域的密钥。
不提供任意 URL、HTTP 代理或关闭 TLS 的选项。未来供应商通过协议/传输接口扩展，需另行审查。

## 凭据保护及原生桥

没有引入第三方安全存储/HTTP 插件或新运行依赖。使用 Android 自带 AndroidKeyStore
（AES-256/GCM/NoPadding，随机 IV，128 位认证标签），应用私有 SharedPreferences 仅保存
密文、IV 和非敏感区域标识，区域通过 GCM AAD 绑定；修改区域会导致解密失败。
Keystore 密钥不可导出，硬件支持取决于设备，不声称所有设备都由 StrongBox/硬件保护。

保存失败不会回退到明文；用户可主动关闭“Keystore 加密保存”选择仅原生内存模式，
退出/重启需重新输入。密钥不保存在 localStorage、sessionStorage、普通 Preferences、
数据库、源代码、APK、Actions 或 Secrets。新 Key 从密码框经原生桥进入 vault 后立即清空输入，
原生 API 从不把 Key 返回 JavaScript。JS/Java 在输入、桥接、解密和发送瞬间仍有内存明文；
不能保证托管运行时立即擦除每份字符串，不抵抗 root、恶意输入法或被攻陷应用/调试设备。

删除/更换会取消活动请求、使迟到结果失效、清除聊天并移除密文和 Keystore 别名。
删除失败时 UI 停用旧配置并明确报告存储错误，不能把错误当作已成功清理；必要时需系统清除应用数据。
已经发出的网络字节不能撤回。不会自动重试或将旧密钥切换到另一区域。

审查固定 Capacitor 8.6.0 源码发现桥接调试日志会包含插件参数，故显式设置
`loggingBehavior: none` 并关闭 WebView 调试。配置/API 失败不回传 Throwable、服务正文、
响应头或密钥，前端仅按预定义错误码显示提示。CI 扫描合成 Key 是否进入设备日志。

Capacitor 的通用原生 HTTP 插件即使不启用 fetch patch 仍可直接调用，因此用本地拒绝插件
覆盖该桥，仅 AgnesAI 开放固定目标网络。原生 CookieHandler 不继承/保存 Cookie，认证只用 Bearer。
原有 Web 端入口、FastAPI Token/Host/Origin/TLS 保护未修改。

## 真实请求与 UI

AI 页有消息列表、输入/发送、模型/区域显示、配置、新建/选择/清除会话、处理中、取消与错误提示。
多轮只发送已完成的 user/assistant 对，原生添加 system 指令。取消、切换、删除密钥后的
迟到分片/结果不会加入上下文。最多保留 5 个内存会话，历史按轮次和长度限制缩减。
关闭页面会取消活动请求；会话不写入本地磁盘或自建云服务。

默认使用普通 JSON 回复；可选 SSE 流式，支持 delta、结束标志、输出上限及截断检测。
真实 HTTPS 使用平台默认信任和主机验证，无自定义信任所有证书、无跨站重定向、无环境代理绕过。
连接10秒/读取45秒/总计60秒超时；请求和响应有长度上限。401/403、429、5xx、断网、
超时、取消、非法格式及重定向分别处理。状态机和原生层均拒绝并发重复提交。

基础 Markdown（标题、列表、粗体、行内/围栏代码）由 React 文本节点渲染。
不使用 innerHTML/HTML 解析、eval 或远程语法脚本；模型链接与图片仅作文本，不自动访问。
浏览器 CSP 仍为 connect-src none，AI 使用受限原生桥避开 CORS，不放宽 WebView 请求源。
Android 仅新增 INTERNET，不增加存储、相机、账号、通知等无关权限。

手机 IME 使用 adjustResize，输入框/主题/底部导航适配安全区域，原有六个学习页面保留。
学习页面持续标识合成演示；AI 页面明确需网络，响应标为模型生成，不能当成真实同步数据。

## 隐私、课程上下文与费用

启用和发送前须明确同意：问题、当前会话历史、主动选择的上下文发往当前 Agnes 服务，
可能消耗额度/计费。服务商保存/使用数据的政策由账号条款决定，不能保证提供商不保存。
默认不附加课程或文件，不自动上传全部资料；可预览并选择合成课程/作业信息。
发送文本明确标注“合成演示数据，不是真实课程”，用户信息与 AI 生成内容分别标识。
既有会话中已发送的上下文会随历史继续发送，新建/清除会话可移除。

预留 LocalContextProvider 扩展接口；PDF/PPT/Word 导入、解析、检索和 RAG 未实现。
不声称有真实资料引用、页码或校园同步，不提供假上传/检索按钮。

## 测试与 APK 验收

```bash
python scripts/run_offline_tests.py
python scripts/run_offline_tests.py --harness
python scripts/verify_e_module.py
node scripts/check_frontend_artifact.test.mjs
node scripts/frontend_ci.mjs --output /tmp/new-web-dist
node scripts/frontend_ci.mjs --android --output /tmp/new-android-dist
python tests/browser_security_smoke.py --dist /tmp/new-web-dist
python tests/browser_security_smoke.py --offline --dist /tmp/new-android-dist
```

原生测试只允许明确 `scholarosSynthetic=true` 的合成模拟器，防止误清理个人手机配置。
包含实际 Keystore 保存/重载/删除、AAD 区域防篡改、内存模式、双区 URL、协议/错误/SSE、
响应大小、取消、TLS 错误，以及真实原生桥 UI 多轮/上下文/安全 Markdown/会话切换等。
测试 APK 的 Mock HTTPS 连接仅替代打开连接的工厂；生产 URL 校验和请求编码仍执行。
另有实际127.0.0.1 HTTP Mock 服务做字节往返，只使用合成密钥。测试专用 HTTP 适配器
不进入交付 APK，不改变生产 TLS；这不是 Agnes TLS 握手或真实连通证据。

原有四项离线设备测试保持，INTERNET 检查因本次授权改为存在但离线页面不发请求。
Python 中默认离线 APK 权限拒绝测试保持；新版本仅显式允许 INTERNET，其余系统权限仍拒绝。
APK 检查包名/版本/入口/SDK/签名/ZIP/资源/CSP/许可、桥日志配置、合成Key或凭据样式误打包。
模拟器测试必须无失败/错误/跳过，设备日志扫描通过后才上传 APK/SHA256SUMS/apk-manifest.json。

构建 run、完整提交、文件大小、APK SHA-256 和 Artifact 以本次最终交付报告为准。
本文件初始提交不宣称 APK 或模拟器已通过；本地 Mock 成功不代表真实 Agnes 已连通。
首轮实际云端构建 [41642477865](https://github.com/Zhaoty24-git/ScholarOS/actions/runs/41642477865)
对应 `1eed1a32bad98f6cfaf98199b7348116d08ebc6b`，Success：18 项模拟器测试无失败/错误/跳过，
包含 Keystore、真实回环 Mock 服务及原生桥多轮/SSE/取消/UI 检查；设备日志未发现合成凭据。
同提交离线 CI [41642477752](https://github.com/Zhaoty24-git/ScholarOS/actions/runs/41642477752)
的 Python 与前端 job 均成功。后续整理提交的最终产物以交付报告和其对应 Artifact 为准。
整理提交的 Android 运行 `41643334539` 长时间未结束，公开页面无阶段日志，未确认根因；
随后为 SDK/编译/模拟器阶段增加独立超时，并在新 runner 重新完整执行。未缩减18项验收或跳过失败。

## 手机验收与限制

下载成功 run 对应 Artifact ZIP，核对 apk-manifest.json / SHA256SUMS，再安装
`ScholarOS-0.2.0-dev-debug.apk`。不需要电脑、Python 或后端服务器。
Debug 签名跨运行可能不同，不能保证覆盖旧测试版；必要时先卸载，卸载会清除本地配置。
正式签名/Release、真实手机安装与真实 Agnes API 均需分别验收。
打开 AI 页，核对国内站域名，同意隐私/费用，自己输入新 Key，选择 Keystore 或仅内存，
先发送一个不含私人资料的短问题，再验证多轮、流式、取消和删除。
不要把 Key、含 Key 的截图、请求头或日志发给 Codex；测试完可在提供商控制台撤销测试 Key。

当前不包含真实校园认证/课程同步、完整文件导入/RAG，不创建收费后端或正式密钥，不自动合并。
