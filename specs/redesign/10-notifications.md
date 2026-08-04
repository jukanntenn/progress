# 10 · 通知

## 决策:Channel/Renderer/Dispatcher 彻底正交 + 经典 TOML discriminated union

通知系统三关注点**完全正交**:Event(纯数据)、Renderer(纯函数)、Channel(纯传输)。notification channels 用经典 Pydantic discriminated union TOML 形态。

## 与 core/reports 的接口(事件派发管道)

### 事件来源(两个)

通知系统消费两类事件,都通过 `RunResult.events` 进入管道:

| 事件来源 | 类型 | 产出方 |
|---|---|---|
| integration 直接产出 | `ProposalEvent`/`ChangelogEvent`/`DiscoveredRepoEvent` | 各 integration 的 `run()` |
| 报告管道产出 | `ReportEvent` | `cli/reports/pipeline` 聚合完 reports 后构造 |

### core.py 的派发编排

```python
# cli/core.py
async def run_notifications(outcome: RunOutcome, cfg) -> None:
    channels = build_channels(cfg.notification)  # 从 config 构造启用的通道
    renderer = JinjaRenderer()
    dispatcher = Dispatcher(channels, renderer)
    for event in outcome.all_events():
        await dispatcher.dispatch(event)
```

`outcome.all_events()` 收集所有 integration 的 `RunResult.events` + reports pipeline 产出的 `ReportEvent`。

### 通道配置边界

- **通道配置**(`[[notification.channels]]`)由 spec 02/10 的 `NotificationConfig` 定义,核心统一管理。
- **integration 不关心通道**:integration 只产出事件,不关心事件发到哪些通道、通道的连接参数(webhook URL、SMTP、收件人)等。
- **通道启用/禁用**:Dispatcher 只对启用的通道(`c.enabled`)派发。
- **通道特定元数据**(如 email 的 `at-users`、feishu 的 `at-users`)通过 `ChannelPayload.metadata` 承载,由 Renderer 从事件中提取。

### batch 派发与通知频率(与 spec 09 协同)

repo_update 类型的 `ReportEvent` 可能因 MarkPost batch 切分而**派发多次**——每个 batch 一个 `ReportEvent`(携带 `batch_index`/`total_batches`)。其他事件类型(proposal/changelog/discovered)各派发一次。

详见 spec 09 的"Batch 切分与按 batch 派发通知"。

## 三关注点分离(跳出现有锚定的纯设计)

当前 N×M 矩阵(ConsoleMessage/EmailMessage/FeishuMessage × 普通/proposal)是病根。纯设计:

```
事件(Event)         → 发生了什么(纯数据,领域语义)
        │
   渲染(Renderer)    → 把事件渲染成"某渠道的目标格式"(纯函数,Event+format→payload)
        │
   渠道(Channel)     → 投递已渲染的载荷到目标地址(纯传输,payload+target→result)
```

三者**完全正交**:Event 不知 Channel,Channel 不知 Event,Renderer 是桥梁。

### Channel(纯传输,不知事件不渲染)

```python
# cli/notifications/base.py
class Channel(Protocol):
    """投递载荷到目标。不知事件类型,不做内容渲染。"""

    name: str  # "email" | "feishu" | "console"

    async def send(self, payload: ChannelPayload) -> SendResult: ...


@dataclass
class ChannelPayload:
    """渠道无关的已渲染载荷。"""

    title: str  # email subject / feishu header / console line
    body: str  # 已渲染目标格式正文
    content_type: ContentType  # HTML / PLAIN_TEXT / CARD_JSON
    metadata: dict = field(default_factory=dict)  # 渠道特定投递参数(recipients / at-users)


@dataclass
class SendResult:
    ok: bool
    error: str | None = None
```

### Renderer(纯函数桥梁)

```python
# cli/notifications/renderer.py
class Renderer(Protocol):
    """把事件渲染成某渠道格式的载荷。纯转换,无 IO。"""

    def render(self, event: Event, format: ContentType) -> ChannelPayload: ...
```

- Jinja2 模板:`templates/{event_kind}/{content_type}.j2`。
- 纯函数(无 async、无 IO),易测。
- **模板矩阵替代 N×M 类矩阵**(声明式,非类矩阵)。

### Dispatcher(编排)

```python
# cli/notifications/dispatcher.py
class Dispatcher:
    def __init__(self, channels: list[Channel], renderer: Renderer): ...

    async def dispatch(self, event: Event) -> DispatchOutcome:
        # 1. 查事件应发哪些渠道
        # 2. 对每个渠道:renderer.render(event, channel.format) -> payload
        # 3. 并发 asyncio.gather(*[ch.send(payload) ...])
        # 4. 聚合 SendResult -> DispatchOutcome
```

### 决策理由(对比受锚定的设计)

| 维度 | 受锚定设计 | 纯设计(采纳) |
|---|---|---|
| Channel 知道事件吗 | 模糊(渲染塞 Channel 附近) | **不知**(纯传输) |
| 渲染在哪 | `(Message, Channel)` 交叉点 | **独立 Renderer 纯函数** |
| 新增事件类型 | 可能要动 Channel | **零改 Channel**(加模板) |
| 测试 | 构造 Message+Channel | mock Channel 验证 payload |

## Event(纯数据)

```python
# cli/notifications/events.py
@dataclass
class ReportEvent:
    kind: str = "report"
    title: str
    summary: str
    repos: list[ReportRepo]


@dataclass
class ProposalEvent:
    kind: str = "proposal"
    ...


# ChangelogEvent / DiscoveredRepoEvent 类似
```

## 渠道实现修复

| 渠道 | 病根 | 修复 |
|---|---|---|
| **email** | `server.close()` 后 `quit()`(应二选一);`connect()` 失败仍 `quit()` | aiosmtplib context manager 或 `quit()` 单独(源码核实 `smtp.py:838-853` quit 内部调 close) |
| **feishu** | ~250 行无类型 dict 字面量拼 card JSON | Pydantic 模型描述 card |
| **console** | `print` 绕过日志栈 | structlog(呼应 04) |
| **通用** | `Message.send` 吞所有异常 + `fail_silently=True` 默认 | `send` 不吞异常;Dispatcher 收集失败返 `DispatchOutcome` |

## notification channels TOML 格式(经典 discriminated union)

```toml
[[notification.channels]]
type = "console"
enabled = true

[[notification.channels]]
type = "email"
enabled = false
host = "smtp.example.com"
port = 465
user = "..."
password = "..."                    # SecretStr
from_addr = "..."
recipient = ["a@x.com", "b@x.com"]  # 多接收者(满足一份报告发多个接收者)
starttls = false
ssl = true

[[notification.channels]]
type = "feishu"
enabled = false
webhook_url = "..."                 # SecretStr
```

### 决策理由(源码核实)

- 实测 Pydantic 2.x discriminated union **接受**此形态(list-of-dicts with `type` key)。
- TOML round-trip 干净。
- openapi schema 标准 oneOf+discriminator。
- 多接收者由 email channel 内的 `recipient = [...]` 字段满足(一份报告发多个接收者)。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| `[[notification.channels.email]]`(type 为 key,下方多实例) | 实测产生 `{channels:{email:[...]}}`(dict-of-lists),Pydantic discriminated union **拒绝**(期望 list-of-dicts) |
| Apprise 统一后端 | URL scheme 配置与 Pydantic/JSON Schema web 编辑器不一致;sync requests 内部 + async_notify 走线程;3 渠道 per-channel 不重;SecretStr 天然脱敏 vs Apprise URL 手写 |

## 密钥 SecretStr

channel 凭据(SMTP password、Feishu webhook_url)用 SecretStr(02 已定)。删手写脱敏。

## 文件结构

```
src/progress/cli/notifications/
├── base.py           # Channel Protocol + ChannelPayload + SendResult + ContentType
├── renderer.py       # Renderer Protocol + Jinja2 渲染
├── dispatcher.py     # Dispatcher + DispatchOutcome
├── events.py         # Event 类型(纯数据)
├── config.py         # NotificationConfig(discriminated union, SecretStr)
├── channels/
│   ├── email.py      # EmailChannel(只 send HTML payload via SMTP)
│   ├── feishu.py     # FeishuChannel(只 send card JSON via webhook)
│   └── console.py    # ConsoleChannel(只 log text payload)
└── templates/
    └── report/       # ReportEvent 模板(归属通知系统,不属任何 integration)
        ├── plain_text.j2
        ├── html.j2
        └── card_json.j2

# 各 integration 的通知模板在 integration 自己包内:
src/progress/integrations/{name}/templates/notifications/{event_kind}/
    ├── plain_text.j2
    ├── html.j2
    └── card_json.j2
```

### 通知模板归属(内聚原则)

- **`report/*` 模板**(ReportEvent 的渲染)归属通知系统核心——因为 `ReportEvent` 是聚合报告事件,不归属任何单一 integration。
- **`proposal/*`、`changelog/*`、`discovered_repo/*` 模板**归属各自 integration——因为它们渲染的事件类型是 integration 专属的业务事实。
- Renderer 通过注册表动态发现 integration 的通知模板目录(`_collect_integration_notification_dirs`,镜像 spec 09 的报告模板发现机制)。

### i18n 契约

- 所有通知模板中用户可见的文本必须用 `{{ _("文本") }}` 包裹。
- 模板渲染时由调用方(Renderer)传入 `language` 参数(来自 `cfg.language`)。
- 翻译文件(`.po`/`.mo`)位于各 integration 的 `locales/{locale}/LC_MESSAGES/` 目录下。
- integration 专属事件的翻译键归 integration 自己;`report/*` 模板的翻译键归通知系统核心。

## 删除清单

| 删除 | 理由 |
|---|---|
| `Console/Email/FeishuMessage` + `*ProposalMessage`(6 类) | 模板矩阵替代 |
| `factory.py` 3 重复 match 函数 | Renderer 替代 |
| `create_channel` 死代码 | Dispatcher 直接用 channels |
| `*Context` NamedTuple 三套 | Renderer 替代 |
| Feishu ~250 行无类型 dict | Pydantic card 模型 |
| `Message.send` 吞异常 | send 不吞,Dispatcher 收集 |
