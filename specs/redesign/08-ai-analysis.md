# 08 · AI 分析

## 决策:Pydantic AI(结构化输出抽取)+ json_repair 兜底

弃当前 shell-out 到 claude/codex CLI,改用 **Pydantic AI** 做结构化输出抽取,保留 **json_repair 兜底**保证稳定性。

## 第一性原理:这是抽取任务,不是 agent 任务

当前 prompts 全部是"文本→JSON"抽取,**禁用 agent 能力**:
- `analysis_prompt.j2:1`:"analyze via stdin, NOT files... current directory is unrelated"
- `proposal_prompt_base.j2:18`:"MUST NOT invoke tools, produce JSON immediately and exit"
- `runner.py:22-31` 启动 `codex exec --full-auto`(给完整自主权限)然后又禁止使用——纯浪费。

**不需要**:文件读写、工具调用、多步推理、沙箱。**需要**:单次模型调用 + 结构化输出 + 校验 + 重试。

这是**结构化输出抽取**(structured output extraction),用 agentic coding CLI 是"用大炮打蚊子"。

## Pydantic AI

### 选型理由(源码核实)

- **async-first**:`Agent.run()` 是 coroutine(`README.md:88-94`)。
- **结构化输出**:`output_type=Pydantic模型`,验证失败自动重试(`_output.py:932-949` 校验 + `_output.py:121-179` 重试)。
- **provider 源头约束**(最强保障):OpenAI `response_format={'type':'json_schema'}`(`models/openai.py:968-971,1507-1516`);Anthropic `output_config`(`models/anthropic.py:794,2210-2212`)——模型在 API 层被约束只能产出符合 schema 的 JSON,**畸形 JSON 在结构上不可能产生**。
- **多 provider**:Anthropic/OpenAI/Groq/Ollama/...(`pydantic_ai_slim/pydantic_ai/models/`)。
- **稳定**:v2.10.0(2026-07-14),Pydantic 团队出品。
- **内置 OTel/Logfire 集成**:与 04 契合。

### 结构化输出的保障链(比当前 regex+repair 更强)

| 层 | 机制 | 当前方案对比 |
|---|---|---|
| 1. Provider 源头约束 | API 层 schema-constrained,畸形 JSON 不可能产生 | 当前:LLM 自由输出,祈祷像 JSON |
| 2. Tool-call 抽取 | SDK 直接返回已解析 dict(`models/openai.py:1100-1111`) | 当前:正则提 `{...}` |
| 3. Pydantic 校验 | `SchemaValidator`(`_output.py:932-949`) | 当前:无 |
| 4. 校验失败自动重试 | 带错误反馈再要一次(`_output.py:121-179`) | 当前:无 |
| 5. 轻量清理 | strip markdown fence(`_utils.py:798-806`) | 当前:`json_repair` |

## json_repair 兜底(强制,保稳定性)

**保留 json_repair 作为最后防线**,因用户明确诉求"不希望替换后失去稳定性"。

### 实现

在 Pydantic AI 的 `output_validator` 里,Pydantic 解析失败时先用 `json_repair.repair_json` 抢救一次再校验(约 5 行):

```python
@agent.output_validator
def validate_with_repair(output: str) -> AnalysisResult:
    try:
        return AnalysisResult.model_validate_json(output)
    except ValidationError:
        repaired = json_repair.repair_json(output, return_objects=True)
        return AnalysisResult.model_validate(repaired)  # repair 后再校验,失败仍 ModelRetry
```

### 决策理由

- Pydantic AI **无内置 JSON Repair**(grep 全零命中)。
- 对不支持 schema 约束的弱 provider(如某些 Ollama 本地模型),源头约束失效,只剩 fence-strip + Pydantic parse + 1 次重试——此时 json_repair 是关键兜底。
- 双保险:源头约束的预防 + json_repair 的治疗。零稳定性回归 + 收益全拿。

### 重试预算

Pydantic AI 默认校验失败重试 **1 次**(`agent/__init__.py:141-147`)。保持默认(源头约束让失败极少)。

## provider 配置

### Pydantic AI model 字符串(单一真相源)

```toml
# config.db.toml / config 表 core section
[analysis]
provider = "anthropic"             # 或 "openai" 等
model = "claude-sonnet-4"          # Pydantic AI model 字符串
api_key = ""                       # SecretStr(Web 类,用户轮换)
language = "en"
```

替代当前散落三处的 provider 字符串(`config.py` validation + `analyzers/__init__.py` 工厂 + `runner.py` `_PROVIDER_BASE_ARGS`,已漂移)。

### API key 归属:Web 类

AI provider API key 是**用户会改**的(轮换)→ Web 类(config 表 core section,SecretStr)。替代当前 Ansible 管的 claude/codex CLI 凭据。

## prompt 仍用 Jinja2 模板

prompt 内容(`analysis_prompt.j2` 等)逻辑正确,只是调用方式错。保留 Jinja2 模板渲染 prompt,但渲染后**喂给 Pydantic AI agent**(而非 stdin)。`{% extends %}` 复用、`language` 参数等不变。

## 测试:TestModel(源码核实)

Pydantic AI 自带测试工具,免真实 LLM API:

| 工具 | 位置 | 用途 |
|---|---|---|
| `TestModel` | `models/test.py:62` | 返回 canned 响应,无网络;自动调所有 tool |
| `FunctionModel` | `models/function.py:46` | 自定义函数控制响应序列 |
| `agent.override(model=...)` | `agent/__init__.py:1708` | 上下文管理器,临时换 model/deps |
| `capture_run_messages()` | `_agent_graph.py:2044` | 捕获完整消息序列断言 |
| `ALLOW_MODEL_REQUESTS=False` | `models/__init__.py:975` | 全局锁,防意外真实调用 |

```python
with agent.override(model=TestModel()):
    result = await agent.run("...")
# 断言 TestModel.last_model_request_parameters
```

## 业务指标

Pydantic AI 内置 OTel 集成,自动产 span。业务指标 `record_analysis`(duration/input_size/failures)用 `@observed` 装饰器(04 定)保留。

## Docker 连带

镜像**不再装 claude/codex CLI**(Pydantic AI 通过 API 调用,不需 CLI)。⑭镜像大瘦身 + 消除供应链风险。

## 文件结构

```
src/progress/cli/ai/
├── __init__.py
├── agent.py        # Pydantic AI Agent 封装 + output_validator(json_repair 兜底)
└── prompts/        # Jinja2 prompt 模板
```

## 删除清单

| 删除 | 理由 |
|---|---|
| `ai/runner.py`(shell-out 到 claude/codex CLI) | 改 Pydantic AI |
| `ai/analyzers/`(claude_code/codex/mock analyzer) | 统一 Pydantic AI |
| `_PROVIDER_BASE_ARGS` + provider 三处散落 | 单一 model 字符串 |
| `_TRANSIENT_MARKERS` 手写 transient 判断 | Pydantic AI 处理 |
| `AnalysisResultParser._extract_json` 正则 | Pydantic AI + json_repair 兜底 |
| `apply_parser` 类型不健全(`# ty: ignore`) | 强类型 output_type |
