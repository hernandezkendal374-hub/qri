# QRI — Quant Research Intelligence

量化论文情报与研究问题生成系统。QRI 用于发现、聚合和核验研究证据，把论文中的主张转成需要人工审核的研究问题与验证方案。

QRI 的职责是回答：

- 什么问题值得研究？
- 它为什么可能成立，又为什么可能不成立？
- 应该如何证伪，最容易在哪些地方得出假结论？

QRI 不负责生成可交易策略，不决定仓位、敞口或执行方式，也不把统计检验包装成投资建议。

## 产品主链

```text
研究来源
  → Claim / Evidence
  → Candidate Research Question
  → Research Validation Spec
  → 人工审核
  → Export
```

每个候选问题同时保存：

- 普通人能看懂的一句话版本
- 可供研究系统使用的学术定义版本

Research Validation Spec 只描述研究对象、经济机制、反向机制、变量、样本、PIT 要求、统计检验、样本外设计、反证条件、数据需求和偏差风险。交易成本、借券和容量只能作为现实敏感性提醒，不能被写成交易规则。

## 不可突破的边界

- **Evidence > Summary**：重要字段没有原文证据即为 `UNVERIFIED`。
- **Question > Conclusion**：作者主张不是系统结论。
- **Falsification First**：验证方案必须明确可能推翻假设的结果。
- **Human Approval > Automation**：验证方案通过人工审核后才允许导出。
- **Statistical Test ≠ Strategy**：回归、组合排序、安慰剂和样本外检验是研究工具，不是交易策略。
- QRI 数据库与下游美股量化系统保持隔离。

旧版策略孵化和快速回测记录不会被删除，但只作为隐藏的只读归档保留，不参与排名、审核或导出。

## 每日最值得研究

每日排名不读取策略收益或回测指标，只依据：

- 新颖度
- 证据质量
- 证据冲突度
- 可证伪性
- 可检验性
- 数据可得性

系统每日 08:00 自动执行论文筛选任务，也可以在运行概览中手动启动。研究问题按生成日期归档。

## 论文来源

当前论文发现层聚合 arXiv、OpenAlex、Crossref 和 Semantic Scholar，并使用 Unpaywall 补充合法开放全文。单一来源限流或失败不会阻断其他来源；原始来源记录保存在 `paper_sources`，规范化论文保存在 `papers`。

QRI 只分析合法获得的全文。仅有摘要时会明确标为 `ABSTRACT_ONLY`，不会声称已经读取全文。

## 本地运行

需要 Python 3.12+。复制 `.env.example` 为 `.env`，配置数据库和 OpenAI-compatible 模型接口。密钥不得写入代码、README 或日志。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

访问：

- `http://127.0.0.1:8000/dashboard`：运行概览与每日最值得研究
- `http://127.0.0.1:8000/papers`：论文库
- `http://127.0.0.1:8000/claims`：作者主张与原文证据
- `http://127.0.0.1:8000/questions`：候选问题、验证方案、审核与导出
- `http://127.0.0.1:8000/daily-best`：每日研究档案

## 模型配置

```env
PRIMARY_MODEL=claude-sonnet-4-6
REASONING_MODEL=claude-sonnet-4-6
VALIDATION_MODEL=claude-sonnet-4-6
```

- `PRIMARY_MODEL`：论文日常分析
- `REASONING_MODEL`：研究问题生成
- `VALIDATION_MODEL`：Research Validation Spec 生成

`STRATEGY_MODEL` 仅为旧版只读数据兼容保留，不再进入主流程。

## 数据库升级

```powershell
alembic upgrade head
```

迁移 `0010` 为研究问题增加双版本文本，并创建 `research_validation_specs`。已有研究问题会安全回填；旧策略与回测表不会删除。

## 测试与质量检查

```powershell
pytest -q
ruff check .
```

测试覆盖论文聚合、全文状态、证据定位、问题生成、范围约束、可恢复漏斗、双版本问题、验证方案持久化和 AI 调用审计。

## 里程碑

- M0–M2：项目骨架、论文聚合、去重、开放全文获取与解析
- M3–M4：Research Card、Claim 与 Evidence Pointer
- M5–M7：论文比较、候选研究问题、可恢复流水线与中文 Web UI
- M8–M9：每日任务、中文摘要、归档与研究价值排名
- V0.2 基线：Research Validation Spec、人工审核、研究包导出，以及旧策略能力只读归档
