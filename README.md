# QRI — Quant Research Intelligence

量化论文情报与研究问题生成系统。QRI 把大量论文压缩成少量值得人工决策的 Research Brief，而不是逐篇生产研究问题。

## 产品定位

QRI 回答三个问题：什么值得研究、为什么值得研究、怎样证伪。它不负责生成可交易策略，不决定仓位、敞口或执行方式，也不把统计检验包装成投资建议。

## 三速研究引擎

```text
每天扫描约 300 项研究
  → 雷达模式：Title + Abstract + Metadata，无 AI 快筛
  → 侦察模式：Top 20 增量判断与冲突检测
  → 深度研究：Top 0–3 全文、Claim 与 Evidence
  → Research Brief：问题、反证与 Validation Spec
  → 一次人工 Gate：批准 / 暂缓 / 拒绝
```

没有候选达到阈值时，系统明确显示“今日无高价值新增研究问题”，不会为了填满日报而强行生成内容。

### 雷达模式

低成本检查相关性、新颖度、与既有观点的冲突和证据潜力。未改变已有知识的论文直接归档，不获取全文、不调用高阶模型。

### 侦察模式

最多保留 20 项，生成摘要级中文解读，回答“它改变了我们已经知道的什么”。之后再次排序，只有达到阈值的 0–3 项进入深研。

### 深度研究模式

仅对 Top 0–3 获取合法全文，生成 Research Card、Claim、Evidence Pointer、Candidate Research Question 和 Research Validation Spec。

## 主题驱动的增量知识

运行单位由“单篇论文”升级为 `ResearchTheme → Evidence Stream → Research Question`。当前主题包括动量、价值、质量、低风险、微观结构、做空约束、机构与中介资本、机器学习资产定价、事件与信息扩散等。

每篇新论文都会被归入主题，并标记为：

- `NO_CHANGE`：未改变现有知识，自动归档
- `EXTENSION`：已有主题的补充
- `NEW_GAP`：暴露新的研究缺口
- `CONFLICT`：可能改变已有观点的重要冲突

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

## 命令行

```powershell
qri daily --target 300
qri radar --scout 20
qri briefs --top 20
qri prioritize --deep 3
qri fetch --top 3
qri analyze --top 3
qri claims --top 3
qri questions
qri validation-briefs --top 3
```

`qri daily-funnel` 会按上述顺序自动运行，并支持从失败阶段恢复。

## 模型配置

```env
PRIMARY_MODEL=claude-sonnet-4-6
REASONING_MODEL=claude-sonnet-4-6
VALIDATION_MODEL=claude-sonnet-4-6
```

雷达快筛不调用 AI；`PRIMARY_MODEL` 用于侦察与论文分析，`REASONING_MODEL` 用于问题生成，`VALIDATION_MODEL` 用于 Research Validation Spec。`STRATEGY_MODEL` 仅为旧数据兼容保留。

## 数据库升级

```powershell
alembic upgrade head
```

- `0010`：双版本问题与 `research_validation_specs`
- `0011`：`research_themes` 与 `radar_assessments`

旧论文、问题、策略与回测数据均保留。

## 测试

```powershell
pytest -q
ruff check .
```

测试覆盖论文聚合、全文状态、证据定位、范围约束、漏斗恢复、雷达淘汰、主题归档、0–3 深研选择、验证方案和一次性人工决策。
