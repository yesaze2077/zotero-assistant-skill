# Zotero 文献助手

**作者：yesaze · 版本：1.1.1**

本项目采用 [MIT 许可证](LICENSE)，Copyright (c) 2026 yesaze。

让科研新手用自然语言完成 Zotero 从零上手、第一篇论文阅读，以及之后的文献整理、引用、PDF/OCR 和连接排障。由本地 Codex 或 Claude Code 代做可自动完成的操作，真实登录和必要权限提示由本人完成。

**[打开 HTML 使用手册](docs/index.html)** · [Skill 入口](SKILL.md) · [能力来源目录](registry.json)

HTML 为单文件离线手册，包含导航、搜索、可复制的提问示例和打印样式。在 GitHub 上下载 `docs/index.html` 后，用浏览器打开即可；查看源码页面不会执行手册交互。

## 安装：直接告诉助手

先在本机打开已经安装并登录的 Codex 或 Claude Code，把下面这段话交给它：

> 请检查并从 https://github.com/yesaze2077/zotero-assistant-skill 安装完整 Zotero Skill。SKILL.md 在仓库根目录，安装名称为 zotero，请一并保留 scripts、references、agents、lessons、tests、registry.json 和使用手册。若已安装，先比较差异并保留原版本与个人状态，不覆盖。完成后检查 Skill 是否可发现，并带我从当前环境继续上手。我没有技术背景，请直接代做安全操作，不让我复制终端命令。

给安装助手的说明：先检查实际客户端 Skill 目录。Codex 有官方 `skill-installer` 时使用其 GitHub 安装脚本，参数为 `--repo yesaze2077/zotero-assistant-skill --path . --name zotero`；根目录安装优先完整下载，安装后对照仓库文件清单验证。不要只复制 SKILL.md。新技能可能在下一轮对话或重新加载会话后才可发现。Claude Code 按当前官方 Skill 机制安装到名称为 `zotero` 的目录；不要把 Skill 安装当成 MCP 已配置。

## 第一次这样用

> 使用 $zotero，检查我已经安装了什么，补齐必要的 Zotero、浏览器 Connector 和 MCP。带我选一篇有 PDF 的论文，完成一次阅读、一条带页码的摘录、一张研究卡片和一次可追溯引用。一次只让我做一个必要动作，沿用已有文献和配置。

之后直接说问题，例如“找出这个集合的研究方法差异”“这篇扫描件无法搜索，帮我做 OCR 副本”“Word 没有 Zotero 标签页，帮我排查”。不必每次重新走完整安装教程。

## 实际范围

| 能力 | 完成标准与条件 |
|---|---|
| 从零安装 | 官方 Zotero、所选浏览器 Connector、唯一选定 MCP；复用已安装组件 |
| 连接与读库 | 分别验证 Local API、MCP 协议和当前客户端实际工具调用 |
| 元数据 / 摘要 / 附件 / 批注 | 读取真实条目；个人本机库是内置读取适配器的默认范围 |
| 全文与研究卡片 | 定位真实 PDF、核对页覆盖和关键证据；来源标记 Full Text / Abstract / Metadata / Inference |
| OCR | 调用已安装 OCRmyPDF，生成新副本；检查源件未变、页数和文字，并抽查识别质量 |
| 导入、分类与引用 | 在明确授权范围内使用 Zotero 支持的操作，逐批读回；Word 动态引用单独验收 |
| 发现新 Skill | 使用时到期检查；每周后台检查需要用户选择并由客户端另行创建自动任务 |
| 经验积累 | 当前用户授权后，保存已验证、去隐私、适用条件清楚的方法；外部升级另经确认 |

本仓库提供指令、索引和本地辅助脚本，**不捆绑 Zotero、MCP Server、OCR 引擎、模型或索引中的外部 Skill**。缺失组件按当前任务需要安装。`registry.json` 的来源是带日期的审阅快照，收录不等于安装、启用或持续兼容；`available-if-installed` 也不证明新电脑已经具备该工具。

macOS 是当前主要验证平台。Python 辅助脚本需要 Python 3.10+，其中状态锁使用 POSIX `fcntl`；Linux 的安装和 GUI 流程需重新核验，Windows 原生 Python 不能直接运行这些状态脚本，助手须按参考文档走系统原生诊断。不要把 macOS 测试称为全平台兼容。内置本机适配器使用个人库 `users/0`；群组库需要单独解析正确库范围。

## 隐私与数据流

本机 Local API 不需要 Zotero 云端 Key。**本机读库不等于 AI 全程离线**：助手把所选论文内容发送给模型分析时，数据处理取决于你使用的 Codex/Claude 服务及其设置。在线 OCR 是另一项上传，需先说明文件范围、服务和费用再取得同意。

不直接修改 Zotero 数据库，不覆盖原 PDF 或批注。发布包不含个人库、论文、配置、密钥、使用进度、日志或历史对话；只保留三条经过脱敏的通用经验。测试中的示例路径和假凭据用于验证隐私拦截，不是真实用户数据。重新分享你自己的安装副本时，也须排除运行状态并审阅新增经验。详见 [隐私与发布范围](PRIVACY.md)。

## 文件与验证

- `SKILL.md`、`agents/`：发现入口与客户端展示信息。
- `references/`：安装、连接、第一篇体验、阅读、分类、PDF 和更新流程。
- `scripts/`：只读诊断与读取、PDF 副本处理、可续接上手进度。
- `registry.json`、`lessons/`：来源索引与通用方法。
- `tests/`：离线回归与可选真实 OCR 冒烟，测试材料在临时目录自行生成。
- `docs/index.html`：用户手册；`requirements-test.txt`：测试依赖。

维护者可在独立 Python 环境安装测试依赖后运行 `python -B -m unittest discover -s tests -v`。这不是普通用户的安装步骤。真实 OCR 测试仅在已有引擎和 Pillow 时运行；未运行会显示 skipped，不会为测试安装系统软件，也不会读取你的 Zotero 文献。

作者署名适用于本助手和手册。外部项目作者、来源及权利说明见 [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md)。
