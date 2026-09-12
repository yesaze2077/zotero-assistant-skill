# 从零到第一篇论文

适用：首次使用、空环境、新电脑，或用户主动要完整入门。基线核验日 2026-09-12；官方入口可能更新，每次真正安装前核对当前系统与页面，不把本机验证扩写成跨平台实测。

## 入口与节奏

先确认正在使用的本地 AI 客户端、操作系统、常用浏览器和是否用 Word。可从当前应用/用户上下文判断的就不再问；只问影响下一步的一个问题。尚未安装/登录 AI 客户端的人无法靠这个 Skill 完成客户端第一次启动，需先完成官方客户端安装和本人登录；本 Skill 从助手已经可以工作的环境开始。[既有客户端的 MCP 配置](mcp-setup.md)单独处理。

运行 `assistant.py doctor` 和 `journey.py status`。doctor 当前是 macOS 优先的只读探针，不检测浏览器扩展是否启用或 Word 动态字段，也不独立证明当前会话 MCP 已加载；这些必须用相应客户端实际操作验证。Windows/Linux 不适用的探针不能判成软件未安装，按系统原生方式检查。

告诉用户“已经可用的部分”和“现在最值得完成的一步”，不要一次发十个设置问题。能安全自动执行就执行；用户请求初次安装已覆盖必要的官方组件和选定 MCP，无需重复要求批准相同范围。下载、安装、首次打开与功能验收分开记录。

## 1. 安装并打开 Zotero

官方来源：[下载页](https://www.zotero.org/download/)、[安装说明](https://www.zotero.org/support/installation)。桌面应用与浏览器 Connector 是两个组件。

**macOS 执行流程：**

1. 检查 `/Applications/Zotero.app` 和用户 Applications，读取实际版本/架构，并检查进程。已有可用版本直接复用，不能为走教程覆盖重装。
2. 缺失时，从官方页面解析匹配 Mac 的当前下载链接，下载到此次任务独立目录。检查下载成功及文件类型，不执行来历不明的安装脚本。
3. 打开 DMG，或由助手用 `hdiutil attach -nobrowse -readonly <下载文件>` 挂载；核对包内 Zotero.app 的签名/来源。目标应用不存在时复制到 Applications；用户目录是需要时的可写替代路径，避免因此修改整个磁盘权限。
4. 用 `open -a Zotero` 或实际应用路径启动。遇到本人才能完成的首次系统确认、管理员密码或登录，由用户完成那一项；不要关闭 Gatekeeper 或批量移除 quarantine 来绕开验证。
5. 观察真实主窗口/版本。任务自身挂载的 DMG 用完可弹出；已有应用、原文献目录和数据库保持原样。`journey` 的 zotero_desktop 只在 application_launch 已验证后记为通过。

Windows：识别架构，在官方下载匹配安装程序，按原生安装流程验证启动。Linux：官方 tarball 解压后运行其中的 Zotero，按官方说明处理桌面入口。两者可由当前可用执行工具代操作；本 Skill 的现有 Mac 验收不代表已在其他系统跑过。

本地使用不要求 Zotero 账号，先完成本地体验。只有用户需要多设备同步/共享时再说明同步范围并由本人登录；不为本地阅读提前购买空间。[官方隐私说明](https://www.zotero.org/support/privacy)、[同步说明](https://www.zotero.org/support/sync)

## 2. 浏览器 Connector

只处理用户实际选择的浏览器。由[官方下载页](https://www.zotero.org/download/)进入对应商店或安装入口，核对来源，不搜名称相似的第三方扩展。操作后检查当前浏览器的启用状态和保存按钮；文件下载、扩展目录存在或商店显示 Installed 都不能代替功能验收。

| 浏览器 | 官方路径与操作 |
|---|---|
| Chrome | 从下载页进入 [Chrome Web Store](https://chromewebstore.google.com/detail/ekhagklcjbdpajgpjgmbionohlpdbjgc)，安装 Zotero Connector，完成浏览器权限提示并启用；必要时固定工具栏按钮 |
| Edge | 从下载页进入 [Edge Add-ons](https://microsoftedge.microsoft.com/addons/detail/nmhdhpibnnopknkmonacoephklnflpho)，安装并启用；使用 Edge 原生条目 |
| Firefox | 在 Firefox 中访问官方 [Connector 安装入口](https://www.zotero.org/download/connector/dl?browser=firefox)，确认浏览器扩展安装；XPI 已下载不等于启用 |
| Safari | 先启动桌面 Zotero，再在 Safari → Settings → Extensions 启用 Zotero Connector；不另找同名商店应用。安装前核对当前系统兼容性。[官方 Safari 说明](https://www.zotero.org/support/kb/zotero_connector_and_safari) |

使用实际可控制的浏览器界面；可代操作时完成。如果缺少扩展管理页控制权限或本人才能确认，打开准确页面后只请用户完成必要点击。不要通过篡改浏览器配置/数据库伪造扩展启用，也不要求关闭浏览器安全机制。

**真实验收**与第一篇论文导入合并：保持 Zotero 运行 → 打开论文落地页 → 点击 Connector 保存到目标集合 → 在 Zotero/API 读回同一篇的标题、作者、年份、DOI及条目类型。若有可访问 PDF，单独检查附件存在和可打开。没有 PDF 可能是访问权问题，不等于 Connector 故障。优先保存论文落地页，避免仅保存 PDF 导致元数据不全。[官方添加条目流程](https://www.zotero.org/support/adding_items_to_zotero)

已有库且先从库内论文体验的用户，可以把 Connector 保存验证记为 deferred，先阅读，不重复导入同一条目。

## 3. 接入本地 AI 助手

按 [mcp-setup.md](mcp-setup.md) 检查/开启 Local API，安装唯一选定 MCP，保留现有客户端设置并完成真实 MCP 调用。该步可与浏览器保存验证按依赖交错进行；浏览器暂不可控不妨碍已存在文献的 MCP 阅读。

完成标准分开：Local API 实际 GET；MCP 初始化与集合工具调用；当前会话工具加载。缺少 Python/pip/uv 仅安装实际必要的一条依赖链，不能同时安装所有替代方案。

## 4. 写作工具

询问或沿用用户实际写作方式。仅用 Zotero 阅读的用户不必安装 Word；已有 Word 用户应获得下面的完整分支。

Word 插件通常随 Zotero 提供，首次启动 Zotero 后重启 Word，检查 Zotero 标签页。缺失时先安全保存正在编辑的文档，不强行结束 Word；退出 Word 后，在 Zotero Settings → Cite → 向下找到 Word Processors → Install Microsoft Word Add-in，重新打开 Word。[官方安装说明](https://www.zotero.org/support/word_processor_plugin_installation)

Mac 仍缺失时检查 Word → Tools → Templates and Add-ins → Global Templates and Add-ins 中的 Zotero.dotm 是否存在并勾选；只按[官方排障说明](https://www.zotero.org/support/word_processor_plugin_troubleshooting)处理目标模板，不重置整个 Word，不删除用户模板。Linux 按官方 LibreOffice 路线处理，不把 macOS Word 操作照搬到 WINE。

在**新建练习文档**里测试第一篇论文：Add/Edit Citation → Add/Edit Bibliography → Refresh → 再次 Add/Edit Citation 可编辑原引用。字段仍可更新才算成功。未指定学校格式时仅选明确标注的练习样式，正式样式另核实；不要点击 Unlink Citations，不用现有学位论文作为测试文件。[官方 Word 使用说明](https://www.zotero.org/support/word_processor_plugin_usage)

## 5. 第一篇体验与完成

进入 [first-paper.md](first-paper.md)。复用已导入的目标论文，每次只带一个阅读动作。OCR、同步、文献格式扩展、模型下载都按这一篇的实际需要处理。

## 可续接状态

`journey.py status` 为纯读；`journey.py record --file RECORD.json` 记录一个实际结果；`journey.py mode daily --reason "用户明确选择跳过引导"` 可在用户要求时进入日常模式。模式切换不代表体验完成，不强行阻止用户处理具体问题。

记录示例（由助手生成，内容需来自本次真实检查）：

```json
{"step":"local_api","status":"verified","evidence":{"kind":"api","summary":"本机条目和集合 GET 返回有效 JSON","checks":{"items_get":true,"collections_get":true}}}
```

环境步骤：zotero_desktop、local_api、browser_connector、mcp、word_citations。

核心体验步骤：paper_selected、paper_text、reader_practice、research_card、first_citation。核心全部 verified 才能称首次体验完成；浏览器或 Word 可独立 deferred/not_applicable。用户报告完成练习可作 user_report 证据，助手创建文件不能替代用户动作。

状态用 pending / verified / deferred / not_applicable / blocked。摘要不存论文全文、文献 key、个人绝对路径或凭据；文件指向用任务内的非敏感代号，完整研究成果留在用户指定工作区。失败保留已完成步骤，只修必要部分；换设备、切换 AI 客户端/浏览器/写作工具或环境变化时重验相关环境项，在证据摘要注明所验证的客户端。历史上 Codex 的 mcp verified 不能证明 Claude Code 已加载。

当前 Python 辅助脚本依赖 macOS/Linux 文件锁；Windows 使用时先核实兼容执行环境，缺少兼容环境可直接按此流程工作并在任务中记录进度，不把脚本无法启动判为 Zotero 安装失败。不要仅为了运行进度脚本强制安装 WSL。
