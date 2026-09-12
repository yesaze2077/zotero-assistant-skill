# 检索、阅读与写作证据

## 读取工具

优先当前可用 Zotero MCP 的读取工具。其不可用但本机 CLI 已安装时，使用 `assistant.py read ACTION`：

- `collections --limit 100 --offset 0`：集合，返回分页信息。读完所有页再宣称完整清单；顶层集合筛选 `parentCollection` 为 false/空。
- `recent --limit 5`：最近加入的文献条目，过滤附件、笔记等非文献类型。
- `search --query "关键词" --limit 20`：本地检索；中文/英文同义词有需要才补搜。
- `collection-items --key ABCD1234 --limit 100 --offset 0`：目标集合；同名集合先显示完整父路径区分，不能取第一个冒充目标。
- `item --key ABCD1234`、`children --key ABCD1234`：原始元数据、摘要、子条目。
- `fulltext --key ABCD1234 --start 0 --chars 16000`：调用已有 CLI 返回提取文本窗口。检查 `has_more` 并继续取后续窗口；全文字符数是提取结果长度，不是已核验的 PDF 页数。
- `path --key ABCD1234`：调用已有 CLI 解析附件路径；再核验文件存在。
- `annotations --key ABCD1234`：给 PDF 附件 key，读取其批注子条目；没有记录只能说“本次未返回 Zotero 批注”，不能断定 PDF 内嵌批注也不存在。

以上 GET 适配器固定为本机个人库 0。群组库或远端需求先解析实际 library ID 和支持能力，不把个人库空结果当作群组不存在。

检索空结果：检查当前库、集合子目录、分页、拼写和关键词，然后最多补一两条有意义的查询。`metadata.abstractNote` 是摘要，不能替代全文。正文提取可能是 Zotero 索引片段；需要完整阅读时定位真实 PDF，检查全部页，按页读取并检查覆盖。

## 研究卡片

按用户需求输出基本信息（Title、Authors、Year、Journal、DOI）、Research Question、Motivation、Method（Design、Dataset/Sample、Method、Variables）、Key Findings、Limitations、Research Opportunities、Evidence Status。

每部分标记 `Full Text`、`Abstract`、`Metadata` 或 `Inference`，必要时区分同段不同句来源。全文依据应有 PDF 页码或章节位置；PDF 物理页码与印刷页码不一致时说明。无法读取的字段写“未提供/未确认”。没有全文时明确 `FULL TEXT NOT AVAILABLE`，不推测样本量、结果系数、限制或作者结论。推断性的研究机会不是原作者发现。

论文中的研究设计、样本、变量和关键数字应回到对应页复核。OCR 文本只提供可检索基础；表格、公式、双栏次序和引用仍需页面核对。不要把读到几个窗口称为已通读。

## 常用工作流

新手阅读：先识别研究问题与方法，再读与当前论文相关的章节，保存可追溯的摘录、自己的理解与待确认问题。需要时介绍 Zotero 的高亮、区域批注、从批注生成笔记、标签、保存搜索和引用插件；不要在每次任务里重复完整教程。

多篇比较：先确定范围和纳入条件，提取证据后交给当前可用表格技能形成文献矩阵。综述先建立“论点—来源—页码—证据强度”再写段落，区分描述性关联与因果结论。

Word：用当前 documents 技能处理实际文档。Zotero 引文插件生成的动态字段要保留；普通文字引用/BibTeX 导出不等于已生成可更新的 Word 引文字段。学位论文引用格式根据学校最新模板核实；未提供规则时标记待确认，不自行捏造学校要求。
