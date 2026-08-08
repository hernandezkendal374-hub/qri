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

## 里程碑

- M0：项目骨架、配置、安全日志、SQLAlchemy 核心模型、LLM/Paper Provider 抽象。
- M1：Semantic Scholar、OpenAlex、Crossref、arXiv 搜索，聚合去重，Paper Registry，真实搜索 CLI。
- M2–M7：全文、结构化提取、Evidence/Claims、多论文推理、端到端 CLI、极简 Web UI。

当前状态：M0 已完成。自动测试覆盖配置默认值、敏感请求头脱敏、严格 Research Card 缺失字段和全部核心表注册。
