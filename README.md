# QRI — Quant Research Intelligence

[English README](README.en.md)

量化论文情报与研究问题生成系统。QRI 把大量论文压缩成少量值得人工决策的 Research Brief，而不是逐篇生产研究问题。

## 产品定位

QRI 回答三个问题：什么值得研究、为什么值得研究、怎样证伪。它不负责生成可交易策略，不决定仓位、敞口或执行方式，也不把统计检验包装成投资建议。

## 三速研究引擎

```text
每天扫描约 300 项研究
  → 雷达模式：Title + Abstract + Metadata，无 AI 快筛
  → 侦察模式：增量研究价值阈值 + 上限（不填满配额）
  → 深度研究：深研阈值 + 上限，允许为 0
  → Research Brief：问题、反证与 Validation Spec
  → 一次人工 Gate：批准 / 暂缓 / 拒绝
```

没有候选达到阈值时，系统明确显示“今日无高价值新增研究问题”，不会为了填满日报而强行生成内容。

### 雷达模式

低成本检查相关性、增量价值、Claim 冲突、证伪价值、投资相关性提示和重复知识惩罚。`LOW_INCREMENTAL_VALUE`、`NO_MATERIAL_CHANGE` 直接归档，不获取全文、不调用高阶模型。

### 侦察模式

只处理达到 Scout 阈值的项目，最多不超过上限，生成摘要级中文解读，回答“它改变了我们已经知道的什么”。之后再次按 Research Value + Investment Relevance 选择深研，达到阈值的项目才进入，数量可以为 0。

### 深度研究模式

仅对达到深研阈值的项目获取合法全文，数量受配置上限限制，也允许为 0；系统随后生成 Research Card、Claim、Evidence Pointer、Candidate Research Question 和 Research Validation Spec。

## 主题驱动的增量知识

运行单位由“单篇论文”升级为 `ResearchTheme → Evidence Stream → Research Question`。当前主题包括动量、价值、质量、低风险、微观结构、做空约束、机构与中介资本、机器学习资产定价、事件与信息扩散等。

每篇新论文都会被归入主题，并标记为：

- `NO_MATERIAL_CHANGE` / `LOW_INCREMENTAL_VALUE`：未改变现有知识，自动归档
- `NEW_CONDITION`：已有主题的新样本、时期或实现约束
- `NEW_EVIDENCE`：为主题补充有用证据
- `NEW_CONFLICT`：可能改变已有观点的重要冲突

每次运行都会留下 `KnowledgeDelta`，因此主题只处理“认知发生了什么变化”，不会每天重复研究整个 Momentum 或 Value 主题。

## Research Brief

完整 Brief 包含：

- 普通人能看懂的一句话问题
- 学术定义版本
- 研究对象、经济机制与反向机制
- Claim / Evidence 证据链
- 变量、样本、PIT、统计检验与样本外设计
- 反证条件、偏差风险和最低数据需求

机器自动完成整份 Brief。人工只在出口做一次决定：`批准进入 Quant System / 暂缓 / 拒绝`。

## 不可突破的边界

- **Evidence > Summary**：重要字段没有原文证据即为 `UNVERIFIED`。
- **Question > Conclusion**：作者主张不是系统结论。
- **Falsification First**：验证方案必须说明什么结果会推翻假设。
- **Statistical Test ≠ Strategy**：回归、组合排序、安慰剂和样本外检验是研究工具。
- 只有人工批准的 Brief 可以导出到下游系统。
- QRI 与下游美股量化系统保持数据隔离。

旧版策略孵化和快速回测记录不会删除，但只作为隐藏的只读档案保存，不参与雷达、排名、审核或导出。

## 每日研究价值

排名不读取策略收益或回测指标，只依据新颖度、证据质量、证据冲突度、可证伪性、可检验性和数据可得性。问题生成还必须通过最低研究优先级与可检验性阈值。

## 论文来源

发现层聚合 arXiv、OpenAlex、Crossref 和 Semantic Scholar，并使用 Unpaywall 补充合法开放全文。单一来源失败不会阻断其他来源。仅有摘要时明确标记为 `ABSTRACT_ONLY`，不会声称已经读取全文。

## 社区攻击雷达（Shadow Mode）

当前只接 Quantitative Finance StackExchange 官方 API，作为独立 `ResearchSourceProvider`。论坛正文始终是 `UNTRUSTED_EXTERNAL_CONTENT`：不执行其中代码、不自动访问外链、不进入 Claim / Evidence、不改变正式每日排名。它只生成默认 `UNVERIFIED` 的 `CommunityObservation`，并可提出待人工审核的 `FalsificationTask`。页面：`/community-attack-radar`。

## 本地运行

需要 Python 3.12+。复制 `.env.example` 为 `.env`，配置数据库和 OpenAI-compatible 模型接口。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

主要页面：

- `/dashboard`：今日研究雷达、漏斗进度与出口决策
- `/papers`：论文库
- `/claims`：作者主张与原文证据
- `/questions`：完整 Research Brief
- `/daily-best`：Research Brief 历史归档
- `/themes`：长期维护的 Research Theme 与 Knowledge Delta
- `/community-attack-radar`：社区弱信号和证伪任务（Shadow Mode）

## 命令行

```powershell
qri daily --target 300
qri radar --scout-max 30 --threshold 0.48
qri briefs --top 30
qri prioritize --deep 5 --threshold 0.62
qri fetch --top 3
qri analyze --top 3
qri claims --top 3
qri questions
qri validation-briefs --top 3
qri community-shadow --query "momentum transaction cost replication"
```

`qri daily-funnel` 会按上述顺序自动运行，并支持从失败阶段恢复。

## 模型配置

```env
PRIMARY_MODEL=claude-sonnet-4-6
REASONING_MODEL=claude-sonnet-4-6
VALIDATION_MODEL=claude-sonnet-4-6
```

雷达快筛不调用 AI；`PRIMARY_MODEL` 用于侦察与论文分析，`REASONING_MODEL` 用于问题生成，`VALIDATION_MODEL` 用于 Research Validation Spec。`STRATEGY_MODEL` 仅为旧数据兼容保留。

增量漏斗可以通过以下环境变量调整。它们都是阈值和安全上限，不是必须填满的数量：

```env
SCOUT_SCORE_THRESHOLD=0.48
SCOUT_MAX_ITEMS=30
DEEP_RESEARCH_THRESHOLD=0.62
DEEP_RESEARCH_MAX_ITEMS=5
DAILY_SCAN_TARGET=300
COMMUNITY_SHADOW_ENABLED=true
```

## 数据库升级

```powershell
alembic upgrade head
```

- `0010`：双版本问题与 `research_validation_specs`
- `0011`：`research_themes` 与 `radar_assessments`
- `0012`：增量知识 `knowledge_deltas`、`scout_assessments`、`investment_relevance`、社区 Shadow Mode 表
- `0013`：Research Question 优先级分层 `P0`–`P3`

旧论文、问题、策略与回测数据均保留。

## 测试

```powershell
pytest -q
ruff check .
```

测试覆盖论文聚合、全文状态、证据定位、范围约束、漏斗恢复、雷达淘汰、主题归档、0–3 深研选择、验证方案和一次性人工决策。

## 开源发布说明

QRI 目前处于可运行的早期版本，欢迎研究者、数据工程师和量化开发者一起改进。公开仓库不包含本地 `.env`、数据库文件、下载的 PDF 或 `data/` 原始资料；请使用 `.env.example` 配置自己的环境。

QRI 的输出是可审计的研究线索和验证说明，不是投资建议、交易信号或收益承诺。项目默认不连接券商、不下单，也不会把统计检验自动包装成可交易策略。任何进入下游量化系统的内容都必须经过人工审核。

贡献流程、报告安全问题和本地开发约定分别见 [CONTRIBUTING.md](CONTRIBUTING.md)、[SECURITY.md](SECURITY.md) 和 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。项目采用 MIT License，见 [LICENSE](LICENSE)。
