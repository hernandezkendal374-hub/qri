# QRI — Quant Research Intelligence

量化论文情报与研究问题生成系统。QRI 发现、聚合、解析与比较学术论文，最终只生成需要人工审查的 Candidate Research Question。它不连接现有量化系统，不回测、不交易，也不把作者结论当作事实。

## 不可突破的边界

- Evidence > Summary：重要字段没有原文证据即为 `UNVERIFIED`。
- Question > Conclusion：第一阶段只保存 `AUTHOR_CLAIM`，禁止自动生成 `SYSTEM_CONCLUSION`。
- Human Approval > Automation：只有 `HUMAN_APPROVED` 的问题才允许导出。
- QRI 数据库与现有美股量化研究系统严格隔离。

## 本地开发

需要 Python 3.12+。复制 `.env.example` 为 `.env`，按需填入密钥；任何密钥都不能写入代码、README 或日志。

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

PostgreSQL 是目标数据库；本地测试可使用 SQLite。若已安装 Docker，可执行 `docker compose up -d` 后运行迁移。

```powershell
alembic upgrade head
qri search "momentum anomaly US equities"
qri fetch --top 3
qri analyze --top 3
qri claims --top 3
qri questions
```

搜索会并发调用 Semantic Scholar、OpenAlex、Crossref 和 arXiv。单个来源限流或超时只产生告警，不阻断其他来源；原始来源记录会完整保存在 `paper_sources`，规范论文保存在 `papers`。

## 里程碑

- M0：项目骨架、配置、安全日志、SQLAlchemy 核心模型、LLM/Paper Provider 抽象。
- M1：Semantic Scholar、OpenAlex、Crossref、arXiv 搜索，聚合去重，Paper Registry，真实搜索 CLI。
- M2：Unpaywall、开放访问 PDF 获取、PDF 内容校验、PyMuPDF 解析和全文状态闭环。
- M3：配置化 OpenAI-compatible LLM、严格 Research Card Schema、提示词版本和 AI 调用审计。
- M4：`AUTHOR_CLAIM`、逐字 Evidence Pointer、本地页码/偏移验证、字段验证状态。
- M5：三论文比较、冲突与 Research Gap 分析、Candidate Research Question。
- M6–M7：端到端 CLI、极简 Web UI。

当前状态：M0、M1、M2、M3、M4、M5 已完成。

M1 验收查询 `momentum anomaly US equities` 的实测结果：发现 40 条、去重后 38 篇、25 篇含摘要。Semantic Scholar 在无 API Key 情况下返回 429，但降级隔离生效，其余公开来源正常给出真实论文列表。全文获取属于 M2，因此当前 `With full text` 为 0 是预期结果。

自动测试覆盖：配置与密钥安全、核心表、严格 Schema 缺失字段、DOI/标题规范化、模糊去重、API 重试、API 超时、单来源故障隔离。

M2 实测从真实候选中成功解析 3 篇全文：26、56、37 页，共 287,297 个字符。每份 PDF 都验证 `%PDF-` 文件签名并限制为 50 MB；解析文本保留页码和字符偏移，为 Evidence Pointer 提供基础。全文尝试失败记为 `FULLTEXT_UNAVAILABLE`，已有摘要仍以 `ABSTRACT` 文档保存，模型不得据此声称读过全文。

M3 的默认主模型是 `claude-sonnet-4-6`，通过 `LLM_BASE_URL` 与 `LLM_API_KEY` 接入 OpenAI-compatible API。每次调用保存 requested/returned model、提示词版本、token、延迟、响应哈希和状态。模型输出必须通过 `ResearchCardExtraction` 严格校验，不能确认的字段必须为 `null`。当前本机未配置这两个环境变量，因此自动测试使用隔离的确定性夹具，真实数据库不会写入模拟 Research Card。

M4 要求模型只提交逐字原文摘录，页码、段落索引和字符偏移由本地 PyMuPDF 解析结果计算。摘录无法在全文中逐字定位时会被拒绝；没有任何有效 Evidence 的 Claim 不入库；`SYSTEM_CONCLUSION` 在 Schema 层被禁止。Research Card 字段没有 Evidence Pointer 时返回 `UNVERIFIED`。这里的 `VERIFIED` 仅表示指针已在本地原文中验证，不表示作者主张已经成为客观事实。M4 使用 3 篇真实 PDF 做隔离夹具验收，得到 3 个 Claims、6 个 Evidence Pointers，真实数据库仍保持无模拟结果。

M5 只对恰好 3 篇已有 Claims 的高价值论文调用 `REASONING_MODEL`（默认 `gpt-5.4`），分别进行一次多论文比较和一次最终问题生成。所有比较项与问题的文献支持必须引用输入集合中的 Claim ID；未知 ID 会使整次结果回滚。问题数量限制为 1–3，必须包含机制、反机制、数据需求、已知风险和四项评分，初始状态固定为 `HUMAN_REVIEW_REQUIRED`。只有人工改为 `HUMAN_APPROVED` 后 `export_candidate_question()` 才能输出标准 JSON，输出后状态变为 `EXPORTED`。隔离验收使用 3 篇真实全文输入，生成 1 条比较、1 个 Candidate Question 和 2 条推理模型审计；真实数据库仍未写入模拟研究结果。
