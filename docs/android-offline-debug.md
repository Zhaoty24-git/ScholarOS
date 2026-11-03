# ScholarOS Android 离线测试版（PR #3）

叠加基线：PR #2 `85c6ea907f2d7a92d48837f3ac4b24df82069c5b`。
分支 `codex/android-offline-apk-pr3`，目标 `codex/ci-offline-tests-pr2`，不自动合并。

## 工程与来源

| 配置 | 实际选择 |
|---|---|
| 应用 | `com.scholaros.app` / ScholarOS / versionCode 1 / `0.1.0-dev` |
| 前端 | 既有 React 19.2.6、TypeScript 6.0.3、Vite 8.0.14，原锁定版本未变 |
| Node / JDK | 24.19.0 / Temurin 21.0.13+9 |
| Capacitor | core/android/cli 8.6.0；App 插件 8.1.2，均 MIT |
| Android | minSdk 24，compile/targetSdk 36，build-tools 36.0.0 |
| Gradle | AGP 8.13.0 / Gradle 8.14.3 |
| 模拟器 | API 35 / google_apis / x86_64 |

Capacitor 版本、Node >=22 要求、包哈希来自官方 npm 元数据；Android/JDK 组合来自
已校验的 Capacitor 8.6.0 模板。Temurin 版本通过官方实际发行标签确认。
Gradle 发行及 wrapper 哈希分别由官方 `.sha256` 核实；wrapper 保留 Apache 版权声明。
首次云端 Android 运行 `41621906822` 因 Kotlin stdlib 1.8.22 与 jdk7/jdk8 1.6.21
重复类失败。按 Maven Central 已核实的 Kotlin BOM 1.8.22 对齐运行库，未跳过重复类检查。
第二轮 `41622391609` 仍报重复类；随后将 Gradle 入口明确限定为 `:app:` 的构建/设备测试，
避免构建依赖库自身的测试 APK，并增强失败任务诊断；应用的四项验收不减少。
模板生成器只在临时目录运行；新增依赖写入 lock，既有锁定版本不变。
安装执行 `npm ci --ignore-scripts`；完整依赖树唯一安装脚本属于 Darwin 可选 fsevents。
App 插件仅用于生命周期、原生返回键与退出，无新增权限；替代方案是自写原生桥。
模板/插件 MIT 许可见 Android THIRD_PARTY_NOTICES.md；原仓库 LICENSE 不变。

## 入口、功能与隐私

Web 保持 `src/main.tsx` → `App.tsx` → `api.ts`，原 Bearer/Host/Origin/TLS 保护不变。
Android 使用 `offline/index.html` → `src/offline/main.tsx` 与 `model.ts`，不导入 Web API。
两者共用 React/TS/Vite 工具链；离线组件与数据独立，不大范围重写 Web 工作台。

首页、课程/作业/通知列表及详情、长列表加载、设置与深浅色切换可操作。
课程包含电力系统分析、电力电子技术基础、自动控制原理。
作业包含已提交、未提交、逾期、缺失/异常日期。资料只展示合成元数据，明确未实现阅读。
不提供上传/同步/连接服务的假按钮；设置明确未连接、未同步，不显示虚假同步时间。
日期按启动时钟生成，只保留在内存，所有内容均为合成演示。

Android Manifest 无网络/存储/账号/相机/通知权限；CSP `connect-src 'none'`。
Capacitor 在 WebView 内拦截 `https://localhost` 的打包静态资源，不启动网络服务。
不含远程开发地址或登录框，不打包账号/Cookie/Token/LLM Key/私人课程。
Python 不随 APK 运行；当前离线模式不需要长期服务器。
导航适配手机/横屏与安全区域，原生返回键返回历史，首页返回退出。

## 构建与安全

`ScholarOS Android Debug` 工作流：push PR3 分支、普通 PR、手动触发（进入默认分支后）。
`contents: read`，checkout 不保留凭据，35 分钟超时，无 Secrets、共享缓存、Release 或部署。
新增 Action 的标签、完整 SHA 和 action.yml 经实际核实：

| Action | 标签 | Commit |
|---|---|---|
| setup-java | v6.1.0 | b843ebf9b913146b38da2eaa7aeddf76074ae1ad |
| upload-artifact | v6.0.0 | b7c566a772e6b6bfb58ed0dc250532a479d7789f |
| android-emulator-runner | v2.38.0 | a421e43855164a8197daf9d8d40fe71c6996bb0d |

checkout/setup-node 沿用已核实 SHA。模拟器 Action 是新增第三方执行代码，仅在无真实
凭据的临时 runner 运行；SDK/系统镜像由官方 sdkmanager 提供，并非完全固定镜像快照。
KVM ACL 仅授予当前临时 runner 用户，不更改仓库或网络安全策略。

流程：干净临时目录离线构建 → Capacitor sync → wrapper 校验/固定 SDK →
assembleDebug/assembleDebugAndroidTest → 实际 APK 检查 → 飞行模式模拟器安装/4 项测试 →
检查 XML 无失败或跳过 → 上传 APK、SHA256SUMS、apk-manifest.json，保留 14 天。
Gradle 失败公开有界诊断，退出码直接传播。没有验收通过就不上传最终 Artifact。

APK 检查包括 ZIP 完整性、aapt2 实际包名/版本/SDK/入口/权限、apksigner 证书验证、
离线资源及敏感文件/在线入口误打包。输出完整构建 SHA、文件大小、APK/证书 SHA-256。
这些检查不代替源码秘密扫描，也不是恶意代码沙箱；CI 不提供真实用户数据。

```bash
python scripts/run_offline_tests.py
python scripts/run_offline_tests.py --harness
python scripts/verify_e_module.py
node scripts/check_frontend_artifact.test.mjs
node scripts/frontend_ci.mjs --output /tmp/new-web-dist
node scripts/frontend_ci.mjs --android --output /tmp/new-offline-dist
python tests/browser_security_smoke.py --dist /tmp/new-web-dist
python tests/browser_security_smoke.py --offline --dist /tmp/new-offline-dist
```

本地与云端证据分别报告。本文件初始提交不声明云端 APK 或设备测试已完成；实际 run、
SHA、APK 大小、校验和及下载入口以交付报告与 Artifact 中的 apk-manifest.json 为准。

## 无需开发环境的手机安装

1. 手机登录 GitHub，打开交付报告中成功的 Actions run。
2. 在 Artifacts 下载对应完整 SHA 的 `ScholarOS-debug-…` ZIP，解压。
3. 核对 SHA256SUMS 与 apk-manifest.json，安装 `ScholarOS-0.1.0-dev-debug.apk`。
4. 如系统提示，临时允许浏览器/文件管理器“安装未知应用”，安装后可撤回。
5. 开飞行模式，测试首页、课程/作业/通知详情、返回、横屏及深色模式。

不需要 Android Studio、电脑、Python 或 Token。Debug APK 仅供测试，不是正式 Release。
临时 runner 自动使用 Debug 签名；不同运行不保证相同签名，因此不保证覆盖升级。
若签名冲突，先卸载旧测试版（清除应用数据）再安装。versionCode 1 不是正式升级序列。
正式签名身份与版本递增须后续单独规划批准。

## 未完成及后续研究

真实校园登录/同步、SSO/MFA/可信设备、会话安全存储、代理附件、文件导入/阅读、LLM
均未实现或未验证。不关闭 TLS/鉴权或传入真实账号试验。
后续先梳理学校协议与允许的客户端行为，利用脱敏协议样本/本地 Mock 研究设备端会话，
再独立设计 Android Keystore、MFA、撤销/清理及目标限制。是否需要服务器取决于后续方案。
模拟器与真机结果分开报告；没有真实手机时必须标注尚未完成真机安装测试。
