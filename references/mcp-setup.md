# 从未配置到实际 MCP 读取

执行者是本地 Codex/Claude Code 助手；所有命令由助手运行，不交给科研用户复制。先确认客户端与操作系统，复用已有 Zotero Server，不重复添加同名或等价服务。下列是 2026-09-12 核验的路径，真正安装前核实当前帮助和版本。

## 1. Local API

启动 Zotero，用固定 loopback 地址实际 GET `http://127.0.0.1:23119/api/users/0/items/top?limit=1` 和 `/api/users/0/collections?limit=1`，检查 HTTP 与 JSON 形状。API 被禁用时，用 GUI 核对 Zotero Settings → Advanced 中允许本机其他应用通信的选项；能代点则完成，确需人工只给这个设置。不要修改 Zotero 数据库，不用 Web API Key 解决本地读取。

## 2. 唯一安装路线

已有 `zotero-mcp`/`zotero-cli` 或等价服务器且可用：验证并复用。当前首选是 [54yyyu/zotero-mcp](https://github.com/54yyyu/zotero-mcp)，对应 Python 包 `zotero-mcp-server`。本助手读适配器已验证 0.11.0，其他版本要重验输出格式，不宣称旧解析器通用。

在包/发行页核实来源、非 archived、近期维护、许可证、当前 Python 要求及 macOS 支持。对首次安装可选用当前受审版本；已有可用版本的升级走用户确认，不因入门流程自动升级。

优先用已存在的 `uv` 独立安装，例如 `uv tool install zotero-mcp-server==<已核验版本>`，然后解析实际的 executable 路径。不要安装 semantic/all 扩展来完成普通读取。[上游安装与可选依赖说明](https://github.com/54yyyu/zotero-mcp#installation)

没有 uv 但有合适 Python：使用任务专用 venv，`<python> -m venv <专用环境目录>`，再由该环境的 Python `-m pip install zotero-mcp-server==<已核验版本>`。macOS/Linux 的命令在 bin 下，Windows 在 Scripts 下；不得使用全局 `sudo pip` 或改系统 Python。运行环境的路径以实际发现结果为准，不能复制另一台电脑的用户名。

Python/uv 都没有时：优先检查 AI 客户端是否提供现成工作区运行时；可用则复用。仍没有才根据系统选一条最小官方运行时安装路线，先检查官方文档，不同时装 Homebrew、pipx、uv 和多套 Python。Homebrew 已有时可用它安装所需组件；没有不强制先装整套 Homebrew。官方入口：[Python 下载](https://www.python.org/downloads/)、[uv 安装](https://docs.astral.sh/uv/getting-started/installation/)。下载成功、依赖安装和 MCP 启动分别验证。

不要盲目运行 `zotero-mcp setup`，它可能面向另一个客户端的配置。已有 CLI `--help` 及 `serve --help` 验证 stdio 启动参数；配置时使用解析后的绝对命令路径，避免 GUI 的 PATH 与终端不同。

## 3. Codex

官方支持 `codex mcp add` 及 `config.toml`。[官方 MCP 文档](https://developers.openai.com/codex/mcp/)

读取实际 Codex 用户配置位置（通常 `~/.codex/config.toml`），只解析相关段，不输出其他密钥。写前备份到私有本地目录并保存校验值。若已有 zotero 段，比较并修复，不覆盖整个文件；若由已安装插件提供同一个服务，先确认可复用，避免再加第二个。

没有同名服务且 CLI 可用时，官方语法为 `codex mcp add zotero --env ZOTERO_LOCAL=true --env ZOTERO_MCP_SCHEMA_REFRESH=0 --env ZOTERO_MCP_TOOLSETS=none -- <实际zotero-mcp路径> serve --transport stdio`。CLI 不可用时可直接按官方格式最小编辑目标 TOML 段，无需为了写一个配置安装另一套 Codex。

首次调用前配置读取白名单。下面仅示意目标段，必须把 command 替换为实际路径，并保留现有其他配置：

```toml
[mcp_servers.zotero]
command = "/resolved/path/to/zotero-mcp"
args = ["serve", "--transport", "stdio"]
startup_timeout_sec = 30
tool_timeout_sec = 120
enabled_tools = ["zotero_get_collections", "zotero_get_collection_items", "zotero_search_collections", "zotero_get_recent", "zotero_search_items", "zotero_search_by_tag", "zotero_advanced_search", "zotero_get_tags", "zotero_get_item_metadata", "zotero_get_item_children", "zotero_get_attachment_path", "zotero_get_item_fulltext", "zotero_get_annotations", "zotero_get_notes", "zotero_synthesize_annotations", "zotero_export_bibliography"]

[mcp_servers.zotero.env]
ZOTERO_LOCAL = "true"
ZOTERO_MCP_SCHEMA_REFRESH = "0"
ZOTERO_MCP_TOOLSETS = "none"
```

工具名以已安装版本 tools/list 为准，未知工具不能默认为可用，也不能为兼容性自动扩大写权限。`none` 仅关闭可选组，不是只读模式；`enabled_tools` 才是这里的客户端白名单。保存后用 TOML 解析和相关配置差异确认没有丢失无关段；回滚只恢复本次目标变更，不覆盖用户随后产生的修改。

## 4. Claude Code 与其他客户端

只有用户选择 Claude Code 时配置它。`claude mcp add --help` 核对当前语法，用 `claude mcp add --transport stdio --scope user --env ZOTERO_LOCAL=true --env ZOTERO_MCP_SCHEMA_REFRESH=0 --env ZOTERO_MCP_TOOLSETS=none zotero -- <实际命令路径> serve --transport stdio` 注册跨项目本地服务；已有项目范围配置则沿用用户范围。通过当前客户端权限机制约束到必要读取工具，不能直接复制 Codex 的 enabled_tools 字段到 Claude 配置，也不能把 `none` 当只读保证。[Claude Code 官方 MCP 文档](https://code.claude.com/docs/en/mcp)

Claude Code 的 Skill 目录链接仅让技能可发现，不会自动创建其 MCP 配置或登录。Claude Desktop、浏览器云对话和其他应用应分别核对官方接入方式；不要把 Claude Code 成功当作其他产品也已连接。初始化只配置用户正在使用的客户端，不一口气改所有客户端。

## 5. 验收和失败层

1. 实际 MCP 初始化成功、tools/list 能看到读取工具。
2. 在用户当前客户端调用一次集合读取，再读一个存在条目的元数据。空库应返回有效空集合，并进入第一篇导入；空库不是失败。
3. 当前对话没有工具时，独立 stdio 测试最多证明服务可用。刷新 MCP/新对话再实际调用；未验证前记录“会话加载待确认”。终端 `get collections` 只作诊断替代，不替换当前会话验收。
4. 定位一篇真实附件、核实路径、读取正文窗口并报告覆盖；不存在 PDF 或无文本转入对应流程。不要强制“空库也必须有全文”才算服务连接成功。

失败时按进程、API、依赖、MCP 协议、客户端加载、附件、文本分层处理。保留已成功部分。用户只想读论文时，可先走已有本地阅读通道，同时准确说明 MCP 尚未验收。
