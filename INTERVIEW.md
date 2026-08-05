# Stripe Sales Copilot — 面试准备文档

## 项目概览

面向 Stripe 销售代表的 AI 赋能 Agent，融合知识图谱遍历、Milvus 向量检索、SQL 客户查询与自建 ReAct Agent Loop。帮助销售回答关于 Stripe 产品、定价、安全与合规的客户问题，给出有源可溯、上下文感知的回答。

**技术栈：** FastAPI + Milvus Lite + networkx + SQLite + OpenAI GPT-4o-mini（function calling）

**规模：** 21 篇知识库文档 | 80 个 KG 实体 | 150 条关系 | 278 个向量 chunk | 6 个 Tool | 14 个 SkillConfig（13 个可分类场景）| 7 张数据库表 | 198 个单元测试

**实测指标（20 轮真实对话，`turn_metrics` 表）：**

```
avg_latency     9865ms      avg_iterations   1.30
avg_tool_calls  1.65        cache_hit_rate   0.424
escalation_rate 0.10        error_rate       0.00
tokens          64708 in / 9873 out (65 次 LLM 调用)
```

---

## 一、整体架构与请求链路

### Q1：描述一次完整的请求处理流程。

**回答：** 请求从 `POST /sales-agent/chat` [`app/main.py:81`](app/main.py#L81) 或 `POST /sales-agent/stream` [`app/main.py:90`](app/main.py#L90) 进入，两者共用同一个生成器 `_run_pipeline()` [`app/graph.py:206`](app/graph.py#L206)。七个阶段：

1. **Session 加载** [`app/context.py:63`](app/context.py#L63) — 从 `session_memory` 表读出 turns + summary。

2. **客户预取** [`app/graph.py:114`](app/graph.py#L114) — 如果请求带 `customer_id`，直接调用 `lookup_customer_tool` 和 `lookup_product_usage_tool`，把结果作为"合成 tool_result"注入。走缓存，第二轮起是 0.8ms。

3. **意图分类** [`app/intent.py:71`](app/intent.py#L71) — 关键词优先（13 个 KG 场景、95 个 question_pattern），置信度 < 0.6 才调 LLM。实测 keyword 路径 0.9ms，LLM 路径 1674ms——差 1800 倍。

4. **Skill 注入** [`app/skills.py:44`](app/skills.py#L44) — 分类结果映射到 14 个 `SkillConfig` 之一，决定 system_prompt、工具白名单、`max_iterations`、升级触发词、输出提示。

5. **ReAct Loop** [`app/graph.py:317`](app/graph.py#L317) — 显式 while 循环：
   - **THINK**：每轮从零重建 messages（不做增量累积），LLM 决定调工具还是合成
   - **ACT** [`app/graph.py:388`](app/graph.py#L388)：先查缓存，未命中才执行工具，成功后回写缓存
   - **OBSERVE** [`app/graph.py:433`](app/graph.py#L433)：连续 2 次工具错误 → 强制合成；否则回 THINK

6. **SYNTH** [`app/graph.py:452`](app/graph.py#L452) — 两次 LLM 调用：`internal_answer`（temp 0.2，给销售看）+ `client_ready_response`（temp 0.4，给客户看，注入客户真名、禁止签名和占位符）。

7. **升级门控 + 持久化** — 规则门控 →（多轮时）上下文 LLM；写 `session_memory` / `sales_interactions` / `turn_metrics`。

### Q2：为什么用 ReAct Loop 而不是固定流水线？

**回答：** 固定流水线（`query → search → format`）无法处理多步推理。比如"ShopHub 是否符合自定义定价条件？"需要：查 customers 表拿年交易额 → 搜知识库拿自定义定价门槛 → 对比给建议。固定流水线无论是否需要都执行全部步骤。

ReAct 让 LLM 自主决策。实测 `avg_iterations = 1.30`——大多数查询一轮就够，复杂的（如 saas_billing 那条 `iter=3, tools=3`）才多走几轮。

**终止条件有三个**：LLM 不再返回 `tool_calls`（自主判断信息足够）、达到 `skill.max_iterations` 硬上限、连续 2 次工具错误。

### Q2b：为什么最后移除了 LangGraph？

**回答：** 项目初期用 LangGraph `StateGraph` 实现 ReAct 循环。后来加流式接口时，`stream_agent()` 写了一套内联循环——因为 SSE 需要在每个阶段 yield 事件，而 `StateGraph.invoke()` 是阻塞的。

结果是**两套实现并存**：`/sales-agent/chat` 走 LangGraph 节点，`/sales-agent/stream` 走内联循环。两者随后漂移了——multi-intent 提示和几处 prompt 修复只存在于流式路径，`run_agent()` 的 sources 提取直接返回空数组，一直没人发现。

重构方案：管线抽成一个生成器 `_run_pipeline()`，yield `(event_name, payload)`。`stream_agent()` 包成 SSE，`run_agent()` 收集 `done` 事件转 dict。**单一实现，两个薄封装。**

`graph.py` 从 1223 行降到 800 行，删掉 467 行（其中 319 行是已不再执行的 LangGraph 节点函数），LangGraph 依赖一并移除。

**教训：** 框架的价值在于它解决的问题。当 `StateGraph` 的阻塞式 `invoke()` 与流式输出冲突时，继续用它反而制造了重复实现。这也是判断"要不要上框架"的一个实用标准——先问它假设的执行模型和你的需求是否一致。

### Q3：知识图谱如何增强检索？

**回答：** KG [`knowledge_base/knowledge_graph.yaml`](knowledge_base/knowledge_graph.yaml)（80 节点 / 150 边）承担两个角色：

**入库阶段** [`app/milvus_loader.py:192-197`](app/milvus_loader.py#L192)：每个 chunk 的元数据通过 KG 遍历增强，写入 `related_products`、`supports_methods`、`complies_with`。存 Checkout 的 chunk 时，metadata 自动带上 "integrates_with Tax, Billing, Link"。

**查询阶段** [`app/kg_retriever.py:95`](app/kg_retriever.py#L95)：用户查询先匹配场景/产品/地区关键词，再从匹配实体做 1-hop 遍历，生成 Milvus 标量过滤表达式：

```
product in ["checkout","tax","billing","link"] and access_level == "public"
```

把向量搜索范围从 278 个 chunk 缩到约 30 个再做相似度计算。

**对比：**
- 无 KG：278 chunks → 向量搜索 → 结果可能混入不相关产品
- 有 KG：278 → 过滤至 ~30 → 向量搜索 → 全部上下文相关

**诚实的边界：** 这是**召回精度换召回率**的取舍。如果 KG 遗漏了某条关系边，正确答案会被过滤掉且永远不可能被检索到。当前 21 篇文档规模下 KG 是手写的、覆盖完整；扩展到数百篇时必须先解决 KG 自动构建（见 Q27）。

### Q4：KG 扩展中 expanded products 和 matched products 是什么关系？filter 怎么拼？

**回答：** 两条路径并行取并集 [`app/kg_retriever.py:156`](app/kg_retriever.py#L156)：

**路径 A（场景 → 产品）：** 遍历每个 matched_scenario 的 `used_for` 边（KG 里共 20 条）。`saas_billing` → `checkout, billing, subscriptions, invoicing`。

**路径 B（产品 → 相邻节点）：** `nx.descendants_at_distance(graph, product_id, 1)` 做 1-hop，沿 `integrates_with`（33 条）和 `cross_sell`（8 条）边。`billing` → `tax, invoicing, checkout, revenue_recognition, sigma`。

去重并排除已在 matched_products 中的，得到 `related_products`。`all_products = matched + related` 拼成表达式 [`app/kg_retriever.py:203`](app/kg_retriever.py#L203)：

```python
quoted = ', '.join(f'"{p}"' for p in products)
return f'product in [{quoted}]'
```

### Q5：RecursiveCharacterTextSplitter 的工作流程？chunk_size 500 不够时怎么办？

**回答：** "递归切分 + 同层合并"两阶段 [`app/milvus_loader.py:271`](app/milvus_loader.py#L271)：

1. **递归切分：** 先用最高优先级分隔符（`\n## `）。某段 > 500 字符就对该段降级用下一级（`\n### ` → `\n- ` → `\n` → `. ` → ` ` → 字符硬切）。≤ 500 的直接保留。

2. **同层合并：** 切完后，同一递归层级的相邻短段通过 `_merge_splits()` 合并，尽量接近 500 但不超过。只用同层分隔符连接，跨层不合并。

**短 chunk：** 500 是上限不是目标。`## Pricing\nFree.`（20 字符）如果无法与同层邻居合并就原样保留。这保证 `##` 标题的语义完整性，代价是极端情况会有 20-30 字符的碎片 chunk。

---

## 二、RAG 实现细节

### Q6：知识库怎么构建的？

**回答：** [`app/milvus_loader.py:244`](app/milvus_loader.py#L244) 的 `ingest()` 六步：

1. **源文档** — 21 篇 markdown，研究自 `docs.stripe.com` 和 `stripe.com/pricing`，覆盖 Payment（8 产品）和 Revenue（7 产品）两条产品线，外加 Connect、Pricing、Security 及 3 篇内部 mock 政策文档。
2. **元数据解析** [`app/milvus_loader.py:87`](app/milvus_loader.py#L87) — 从每篇文档头部解析 Product Line、Product、Topic、Source Type、Access Level。
3. **切分** — `RecursiveCharacterTextSplitter(500, 80)`。
4. **KG 增强** — 从 product ID 出发遍历 KG，注入三个关系字段。
5. **Embedding** [`app/milvus_loader.py:285`](app/milvus_loader.py#L285) — `text-embedding-3-small`，1536 维，批量。
6. **入库** [`app/milvus_loader.py:300`](app/milvus_loader.py#L300) — Milvus Lite，COSINE，100 条/批，共 278 chunks。

### Q7：frontmatter 解析有哪些坑？怎么修的？

**回答：** 最初 `_parse_frontmatter()` 遇到空行直接 `break`（`if not line: break`），导致所有文档元数据都没解析到，`product` 字段全是 "unknown"——于是 KG 增强完全失效，所有 chunk 的 `related_products` 为空。

**修复** [`app/milvus_loader.py:87`](app/milvus_loader.py#L87)：空行改为 `continue`。加 `in_frontmatter` 状态标记：遇到首个匹配 `Key: Value` 的非 `#` 行进入解析模式，之后遇到不匹配的行才退出。正确处理了 `# 标题 → 空行 → Product Line: xxx` 的文档格式。

**这个 bug 的教训：** 它不会报错，只会让整条 KG 增强链路静默降级为纯向量检索。这类"静默降级"是 RAG 系统最危险的 bug——最好的防线是在入库后加断言：随机抽样 N 个 chunk，检查 metadata 非空。

### Q8：Milvus 标量过滤和向量检索的执行顺序？

**回答：** 先标量过滤后向量检索 [`app/milvus_retriever.py:151`](app/milvus_retriever.py#L151)：

1. **标量过滤：** 用倒排索引排除不匹配的 chunk，278 → ~30。
2. **向量检索：** 只在过滤后的子集上算 COSINE 距离。
3. **返回 top-k。**

等价于 SQL 的 `WHERE ... ORDER BY similarity LIMIT k`。区别是 filter 用 Milvus 自己的 expression language，支持 `field in [...]`、`==`、`and`/`or`，不支持 `LIKE`、`JOIN`、子查询。

**追问预判——过滤后候选集小于 top_k 怎么办？** 返回的结果数就少于 top_k，不会自动放宽过滤。这是当前实现的一个真实风险：如果 KG 扩展只匹配到一个冷门产品，过滤后可能只剩 2-3 个 chunk。生产上应该加 fallback——过滤结果数 < top_k/2 时退化为无过滤的纯向量检索。**当前没做。**

### Q9：KG filter 和 access_level filter 如何叠加？

**回答：** [`app/milvus_retriever.py:136`](app/milvus_retriever.py#L136) 用 `and` 拼接：

```python
filters = []
if kg_filter:                          # 'product in ["connect"]'
    filters.append(kg_filter)
if access_level == "public":
    filters.append('access_level == "public"')
filter_expr = " and ".join(filters)
```

3 篇内部文档（`custom_pricing_policy.md`、`mock_security_policy.md`、`sales_playbook.md`）的 `access_level` 是 `internal_mock`，公开搜索中被自动排除。

**这是权限控制的正确位置吗？** 部分是。它保证了 `search_product_info` 不会泄露内部文档。但 `lookup_pricing_tool` 是直接读文件的，绕过了 Milvus——它靠代码里手工切掉 `## Price` 之后的段落 [`app/tools.py:218`](app/tools.py#L218) 来防泄露。两套机制不统一，是个真实的设计债。

---

## 三、Agent 设计

### Q10：解释 Skill 系统的设计理念和实现。

**回答：** Skill 是**配置层不是运行时层** [`app/skills.py:13`](app/skills.py#L13)。`SkillConfig` 是 frozen dataclass，8 个字段：

```python
SkillConfig(
    scenario_id="marketplace",
    display_name="Marketplace / Platform",
    system_prompt="You are a Stripe Connect specialist...",
    required_tools=("search_product_info",),
    optional_tools=("lookup_customer_tool", "lookup_product_usage_tool",
                    "lookup_policy_tool", "lookup_pricing_tool"),
    max_iterations=3,
    escalation_triggers=("custom onboarding", "cross-border payout",
                         "KYC verification", "multi-party payment flow"),
    response_hint="If the customer needs seller onboarding...",
)
```

注册表有 **14 条**：12 个产品场景 + `escalation_request` + `out_of_scope`。后两个 `max_iterations=0`，完全跳过 ReAct 循环。

**为什么不做成独立运行时层？** 会产生两套路由机制（Tool Router + Skill Router），而 LLM 在 ReAct 里本来就能选工具。作为配置的好处：
- 新增场景 = 新增一个条目，零代码
- LLM 自主权保留
- 工具白名单直接决定 function schema 里有哪些函数，LLM **看不到就不可能调用**
- `system_prompt` 注入领域角色

| 维度 | Skill（配置） | Tool（执行） |
|---|---|---|
| 范围 | 一个完整销售场景 | 一个原子操作 |
| 内容 | system_prompt + 工具白名单 + 升级触发词 + max_iter + response_hint | 输入 schema + 函数体 + 描述 |
| 粒度 | 约束 LLM 行为边界 | 执行具体检索/查询 |

### Q11：ReAct Loop 中 THINK → ACT → OBSERVE 的详细实现。

**回答：** [`app/graph.py:323`](app/graph.py#L323) 的显式 while 循环，状态只有三个局部变量：`tool_results`、`iterations`、`done`。

**THINK** [`app/graph.py:326-386`](app/graph.py#L326)：
- 每轮**从零构建** messages，不做增量累积
- 遍历 `tool_results`，把每次调用重建为 `assistant(tool_calls=[...])` → `tool(content=...)` 消息对
- 首轮如果还没调过 `search_product_info` 且该 skill 有 required_tools，追加一条 system 提示做 grounding 引导（**只是提示，不是强制**）
- LLM 返回 `tool_calls` → ACT；不返回 → `break` 进 SYNTH

**ACT** [`app/graph.py:388-431`](app/graph.py#L388)：
- 解析 `tc.function.name` / `arguments`（JSON 解析失败退化为 `{}`）
- **先查 `tool_cache.get()`**，命中直接用
- 未命中 → `TOOL_BY_NAME[name].invoke(args)`
- 异常捕获为 `ERROR: {type}: {msg}` + `is_error=True`，**不中断循环**
- 成功结果写回缓存

**OBSERVE** [`app/graph.py:433-450`](app/graph.py#L433)：
- 统计尾部连续错误数，≥ 2 → 强制合成
- 否则 `continue`，由 while 条件（`iterations < max_iterations`）控制

**这里没有"条件路由"或状态机。** 早期 LangGraph 版本用 `next_action` 字符串（`"call_tool:xxx"` / `"synthesize"`）做节点跳转；现在就是普通的 `break`/`continue`，可读性和可调试性都更好。

### Q12：为什么自建 Agent Loop 而不用 LangChain AgentExecutor？

**回答：** 三个原因：

1. **按场景的工具白名单。** AgentExecutor 默认向 LLM 暴露全部工具。本项目要求 `global_expansion` 场景下 LLM 看不到 `lookup_policy_tool`。自定义循环在 [`app/graph.py:307`](app/graph.py#L307) 调 `get_tools_for_skill()` 限制可见工具——不在 schema 里就不可能被调用。

2. **升级门控的领域逻辑。** [`app/graph.py:523`](app/graph.py#L523) 的三层升级判断同时依赖 SkillConfig 和客户 DB 数据，无法嵌进通用 AgentExecutor。

3. **消息构建的完全控制。** OpenAI 要求严格的 `assistant(tool_calls)` → `tool(result)` 配对顺序。自建循环可以选择"每轮重建"而不是"增量累加"——这个选择直接解决了一类 400 错误（见 Q13）。

**反过来说 AgentExecutor 的优势是什么？** 开箱即用的 callback / tracing 生态、多种 agent type、社区维护的 prompt 模板。如果场景约束不强、不需要定制升级逻辑，用它更快。这不是"框架不好"，是需求不匹配。

### Q13：多轮 tool calling 的消息构建有什么坑？

**回答：** OpenAI 要求 `assistant(tool_calls)` 后面必须紧跟对应 `tool_call_id` 的 `tool` 消息，否则 400。

早期用 LangGraph 的 `Annotated[list[dict], operator.add]` 累加器做消息增量更新。问题是第二轮 THINK 时累加历史变成 `assistant(tool_call) → assistant(tool_call)` 连排，中间缺 tool result，API 直接拒绝。

还踩过两个具体的 400：
- `Missing required parameter: 'messages[1].tool_calls[0].type'` — 重建 tool_call 消息时漏了 `"type": "function"` 和 `"id"`
- `tool_call_ids did not have response messages` — 累加导致配对断裂

**解决方案：** 每轮 THINK **从零重建** messages——`system + user + 遍历 tool_results 重建完整消息对`。`tool_results` 是唯一状态源。

**代价：** 输入 token 随迭代数线性增长（实测最重的一轮 9205 input tokens）。这是明确的取舍——用 token 换正确性。如果要优化，可以只对最近 N 轮保留完整 output、更早的做摘要，但当前 `max_iterations ≤ 3`，不值得引入这个复杂度。

### Q13b：并行 tool call 支持吗？

**回答：** **不支持，当前只取 `choice.tool_calls[0]`** [`app/graph.py:380`](app/graph.py#L380)。

gpt-4o-mini 在一次响应里可以返回多个 tool_call（parallel function calling）。当前实现直接丢弃了第 2 个及以后的调用——LLM 下一轮如果还需要会重新请求，所以不会丢失信息，但会多一轮 LLM 往返。

**为什么当前可以接受：** `avg_iterations = 1.30`，说明多工具需求本来就少。

**要支持的话怎么改：** ACT 阶段改成遍历 `choice.tool_calls`，每个都执行并生成对应的 `tool` 消息；THINK 重建消息时，一个 `assistant` 消息要带上多个 `tool_calls`，后面跟多条 `tool` 消息。改动集中在 `tool_results` 的结构（需要按"轮"分组而不是按"单次调用"平铺）。工具之间无依赖时可以用 `asyncio.gather` 并发执行，能省掉串行 IO 时间。

---

## 四、升级与安全

### Q14：升级门控如何防止误触发？

**回答：** 双重条件必须同时满足 [`app/escalation.py:81`](app/escalation.py#L81)：

**Gate A：场景是升级合格的**（`escalation_triggers` 非空）。14 个场景中只有 **4 个**定义了 triggers：`marketplace`、`tax_compliance`、`pricing_negotiation`、`escalation_request`。

**Gate B：查询含具体触发短语 OR 客户数据达阈值。**

**正例：**

| 查询 | 场景 | 触发 | 升级目标 |
|---|---|---|---|
| "We need custom onboarding for our marketplace sellers" | marketplace | "custom onboarding" | Connect Specialist |
| "Can you help with our VAT return filing?" | tax_compliance | "filing" + "VAT return" | Tax Team |
| "We want custom pricing at $5M volume" | pricing_negotiation | "custom pricing" + volume>$1M | Deal Desk |
| "Connect me with someone who handles enterprise deals" | escalation_request | "connect me with" | Sales Ops / Human Agent |

**反例（正确拦截）：**

| 查询 | 场景 | 为何不升级 |
|---|---|---|
| "What is Stripe Connect?" | marketplace | 场景合格但无 "custom onboarding" 等短语 |
| "Is Stripe secure?" | security_compliance | **场景本身就没有 triggers**，Gate A 直接拒绝 |
| "Our dispute rate is high" | fraud_prevention | **场景本身就没有 triggers** |
| "How does Stripe Tax work?" | tax_compliance | 场景合格但无 filing/registration |

**交易额升级** [`app/escalation.py:114`](app/escalation.py#L114)：从 `customers` 表读 `annual_payment_volume`。> $10M 且场景是 pricing 类 → 强制 Enterprise Sales（覆盖其他规则）；> $1M 且 `pricing_negotiation` → Deal Desk。

### Q14b：为什么 fraud_prevention 和 security_compliance 的 triggers 被清空了？

**回答：** 因为它们在真实测试中几乎每条查询都触发升级。

原来的 triggers 是单词——`"dispute"`、`"fraud"`、`"SOC"`、`"security"`。但 `fraud_prevention` 场景的查询本身就必然包含 "fraud" 或 "dispute"；`security_compliance` 场景的查询必然包含 "security"。**触发词和场景关键词高度重合，Gate B 退化成恒真。**

收紧过程分两步：
1. 单词 → 明确多词短语（`"human"` → `"talk to a human"`，`"onboarding"` → `"custom onboarding"`）
2. 对于触发词与场景关键词本质重合的两个场景，直接清空 triggers

清空后这两个场景永不自动升级，靠 SYNTH 的 `response_hint` 在回答末尾主动询问"要不要帮你联系合规团队"，把决定权交给用户。

**路由表保留了。** `TEAM_ROUTING` 里 "SOC report"、"dispute rate too high" 等条目仍在 [`app/escalation.py:30`](app/escalation.py#L30)——当前不可达，但重新启用只需要往 SkillConfig 里加回 triggers，路由逻辑不用动。

### Q15：trigger 匹配是子串还是分词？边界条件是什么？

**回答：** **子串匹配** [`app/escalation.py:108`](app/escalation.py#L108)：

```python
query_lower = query.lower()
for trigger in triggers:
    if trigger.lower() in query_lower:
        matched_triggers.append(trigger)
```

**边界条件：**
- `"custom onboarding"` 匹配 `"we need custom onboarding for sellers"` ✓
- `"custom onboarding"` **不**匹配 `"custom seller onboarding"`（中间插了词）✗
- `"filing"` 会匹配 `"profiling"` —— **子串匹配的真实误报**，当前靠 `tax_compliance` 场景本身的窄范围兜住

**为什么不用分词/正则？** 简单策略降低误触发，而误触发是这个系统真正的痛点（用户明确抱怨过"escalation 太容易触发"）。代价是变体（"SOC 2" vs "SOC report"）需要额外加为独立 trigger。

**如果要改进：** 用 `\b` 词边界正则解决 "profiling" 问题，用短语的词序无关匹配（所有词都出现且在 N 个词的窗口内）解决 "custom seller onboarding"。当前 40 条触发短语的规模下，人工维护列表还是最可控的。

### Q15b：升级触发后会直接转人工吗？

**回答：** 不会。这是用户明确要求的行为——"即使升级，也给一个简单的 agent 回答说要不要升级"。

流程是：SYNTH 照常生成回答 → 升级门控判定 → `done` 事件带 `escalation_pending: true` → 前端弹确认框（"Connect to Deal Desk" / "No, thanks"）→ 用户点确认才打 `POST /sales-agent/confirm-escalation` [`app/main.py:113`](app/main.py#L113)。

**设计理由：** 误升级的代价（用户被莫名转走、销售被无效打断）远高于漏升级（用户可以再问一次）。把最终决定权交给人，规则只负责"建议"。

---

## 五、数据与持久化

### Q16：数据库 7 张表的关系和设计理念。

**回答：** `data/stripe_sales_copilot.db`：

```
customers ──< customer_product_usage >── stripe_products
    │
    ├──< sales_interactions          sales_policy_updates（独立）
    ├──  session_memory（无 FK）
    └──  turn_metrics（无 FK）
```

| 表 | 行数 | 来源 | 用途 |
|---|---|---|---|
| `customers` | 30 | 原有 | 客户画像：annual_payment_volume、industry、fraud_risk_level |
| `stripe_products` | 26 | 原有 | 产品目录：product_group、complexity_level |
| `customer_product_usage` | 81 | 原有 | 客户-产品关联：usage_status、monthly_revenue、adoption_level |
| `sales_policy_updates` | 20 | 原有 | 销售政策：policy_area、escalation_team、is_active |
| `sales_interactions` | 97 | 原有 | 交互日志，每轮写入 |
| `session_memory` | 119 | 新增 | 会话记忆：turns_json、summary |
| `turn_metrics` | 20 | 新增 | 可观测性 |

**为什么 session_memory 没有外键？** 最初有 `FOREIGN KEY (customer_id) REFERENCES customers`，结果"用户还没选客户就开始对话"这个正常路径直接 `FOREIGN KEY constraint failed`。改法是去掉 FK，并在 `save_session()` 里把 `""` 归一化为 `NULL` [`app/database.py:84`](app/database.py#L84)。

**连接管理** [`app/database.py:27`](app/database.py#L27)：单连接缓存 + `check_same_thread=False` + WAL + `busy_timeout=5000`。WAL 让读不阻塞写、写不阻塞读。

**追问预判——单连接 + 多线程安全吗？** SQLite 在 `check_same_thread=False` 下允许跨线程使用同一连接，但**并发写需要序列化**。当前靠 `busy_timeout` 让冲突的写请求等待 5 秒而不是立即失败。FastAPI 的同步端点跑在线程池里，实际并发写压力很低。真正的生产部署应该用连接池（每线程一个连接）或换 PostgreSQL。

### Q17：Session 记忆的滑动窗口 + 压缩机制怎么工作？

**回答：** [`app/context.py:98`](app/context.py#L98) 的三层分层窗口。

**Token 预算** [`app/context.py:24`](app/context.py#L24)：4000 total，1500 保留给 system prompt + tool schemas + 回答空间，2500 给对话。

**Layer 1 — 摘要（始终包含）：** LLM 压缩的旧轮次，2-4 句英文。保留客户名、业务模式、讨论的产品、痛点、定价决策。约 100-200 tokens。

**Layer 2 — 最近 3 轮原文（优先）：** 逐轮检查预算。某轮超预算时调 `_truncate_to_tokens()` **截断而非丢弃** [`app/context.py:129`](app/context.py#L129)。

**Layer 3 — 旧轮次（有余量才要）：** 截断为 200 字符，仅当剩余预算 > 500 tokens。

**截断策略** [`app/context.py:157`](app/context.py#L157)：二分查找字符边界 → 退到最后一个句号/问号/感叹号。保证不在句子中间切断。

**触发时机** [`app/context.py:191`](app/context.py#L191)：`add_turn()` 后检查总 token > 2500 **且** turns > 3 → LLM 压缩。增量更新：旧摘要 + 新老化的轮次 → 新摘要。

**为什么"截断而不丢弃"？** 丢弃整轮会让 LLM 完全看不到那次交互，可能重复提问。截断至少保留开头——而对话轮次的开头通常就是核心信息（用户的问题本身）。

### Q18：tiktoken 计数 vs LLM 实际消耗一致吗？

**回答：** 不完全一致。项目用 `tiktoken.get_encoding("cl100k_base")` [`app/context.py:28`](app/context.py#L28)，gpt-4o-mini 也用 cl100k_base，所以文本本身的计数是准的。

**不准的部分：** 消息格式的开销。OpenAI 每条消息有固定 overhead（role 标记、分隔符，约 3-4 tokens/条），tool schema 的序列化也占 token，这些 `_count_tokens(text)` 都没算。1500 tokens 的 reserve 就是为了吸收这个偏差。

**现在有更好的做法：** `metrics.record_llm(response)` 直接从 `response.usage.prompt_tokens` 拿真实值 [`app/metrics.py:124`](app/metrics.py#L124)。tiktoken 用于**事前预算**（决定塞多少进 context），usage 用于**事后核算**（成本和监控）。两者用途不同，都需要。

---

## 六、性能与扩展

### Q19：一次查询的延迟如何分解？瓶颈在哪？

**回答：** 这是实测数据，不是估算——`turn_metrics` 表每轮记录分阶段延迟。

**三条真实记录：**

```
saas_billing   keyword  llm=5 iter=3 tools=3  总 16212ms
  preload 0.1 | intent 0.9 | react_loop 4476.9 | synth 11729.1 | escalation 0.7

ecommerce      llm      llm=5 iter=2 tools=1  总 13732ms
  preload 0.1 | intent 1674.4 | react_loop 5754.5 | synth 6298.8 | escalation 0.8

out_of_scope   keyword  llm=0 iter=0 tools=0  总 3ms
  preload 0.1 | intent 0.1
```

**结论：**

1. **SYNTH 是最大头**（6.3-11.7s），因为它是两次串行 LLM 调用（internal 800 tok + client 600 tok）。这两次**互相独立**，完全可以并发——是当前最明确的优化点，预计能砍掉 40% 延迟。**当前没做。**
2. **intent 阶段 0.9ms vs 1674ms** — 关键词路径 vs LLM 路径差 1800 倍。这就是关键词优先策略的价值，一眼可见。
3. **本地操作可忽略** — preload 0.1ms（缓存命中）、escalation 0.7ms（规则匹配）。
4. **out_of_scope 快速通道 3ms，零 token。**

平均 9865ms（20 轮）。比早期文档里写的"2-4 秒"高得多——早期那个数字是没有实测、按单次 LLM 调用估的，实际有 4-6 次 LLM 调用。**这是一个有价值的教训：没有埋点之前，对延迟的直觉估计可以错 3 倍。**

### Q20：如何实现多用户并发？扩展路径？

**回答：**

| 层级 | 并发 | Milvus | 数据库 | Session | 工具缓存 |
|---|---|---|---|---|---|
| Dev（当前） | 1-5 | Milvus Lite（文件锁） | SQLite WAL | SQLite | 进程内 |
| Test | 5-50 | Milvus Docker | SQLite WAL | SQLite | 进程内 |
| Prod | 50-500+ | Zilliz Cloud | PostgreSQL | Redis | Redis |

**瓶颈分析：**
- **Milvus Lite 文件锁**是当前最大瓶颈，`search()` 被串行化。
- **SQLite WAL** 支持多读单写，当前规模够用。
- **工具缓存是进程内的**——多 worker 部署时每个 worker 一份，命中率按 worker 数衰减。`get`/`put`/`invalidate` 三个函数签名不变，换 Redis 是局部改动。
- **KG** 是内存 DiGraph，只读，~10μs/次，永不是瓶颈。
- **OpenAI API** 自带并发。

**切换成本：** Milvus Lite → Docker 只改 [`app/milvus_retriever.py:34`](app/milvus_retriever.py#L34) 一行 URI。

**无状态性：** 每个请求创建独立的 `_run_pipeline()` 生成器，无跨请求共享的可变状态。会话隔离靠 `session_id`，缓存隔离靠 `_store[session_id]` 的两层字典结构——不是键前缀拼接，因为 `lookup_customer_tool` 返回的是客户 PII，结构性隔离比字符串拼接更难出错。

### Q21：LLM 挂了或返回格式错误怎么办？

**回答：** 所有 LLM 调用统一走 `_call_llm_with_retry()` [`app/graph.py:55`](app/graph.py#L55)，3 次重试，指数退避 1.5^n 秒。

**重试判断** [`app/graph.py:80-99`](app/graph.py#L80)：

| 异常 | 处理 | 理由 |
|---|---|---|
| `RateLimitError` (429) | 重试 | 限流是暂时的 |
| `APIConnectionError` | 重试 | 网络抖动 |
| `APIStatusError` ≥ 500 | 重试 | 服务端故障通常暂时 |
| `APIStatusError` < 500 | **不重试** | 400 是请求格式问题，重试不解决 |
| 其他 `Exception` | 重试 | 保守 |

**3 次全失败后的降级：**

| 阶段 | 降级行为 |
|---|---|
| THINK | 发 `error` 事件，`break` 出循环，带着已有的 tool_results 进 SYNTH |
| SYNTH internal | 模板降级：`_summarize_tool_results()` 输出原始工具结果 |
| SYNTH client | 固定话术："Thank you for your question. I'd be happy to connect you with a specialist." |
| 整个管线抛异常 | [`app/graph.py:593`](app/graph.py#L593) 捕获，写 metrics（含 error），发 `error` 事件 |

**为什么 THINK 失败后不重试而是强制 SYNTH？** THINK 失败意味着 agent 无法"思考"下一步。继续循环只会重复失败。强制 SYNTH 至少能基于已有工具结果给出部分回答。

**JSON 解析容错：** intent [`app/intent.py:262`](app/intent.py#L262) 和 escalation [`app/escalation.py:208`](app/escalation.py#L208) 都会先 `removeprefix("```json")` 清理 markdown 包裹，再 `json.loads`，失败则回退到关键词结果 / 不升级。

---

## 七、工程实践

### Q21b：这个项目怎么测试？单元测试和集成测试如何分层？

**回答：** 两层，用 pytest marker 区分。

**单元测试（198 个，约 5 秒，零外部依赖）：**

| 文件 | 单元 | 集成 | 覆盖 |
|---|---|---|---|
| `tests/test_escalation.py` | 46 | — | Gate A/B、触发词匹配、交易额阈值、团队路由 |
| `tests/test_kg_retriever.py` | 39 | — | 关键词匹配、图遍历、filter 构建 |
| `tests/test_intent.py` | 23 | 4 | 意图分类、out-of-scope、上下文继承 |
| `tests/test_tool_cache.py` | 21 | — | 键稳定性、TTL 过期、会话隔离、容量边界 |
| `tests/test_skills.py` | 19 | — | 注册表完整性、工具名合法性、KG 节点覆盖 |
| `tests/test_context.py` | 18 | — | Token 预算、截断、分层组装 |
| `tests/test_tools.py` | 16 | 1 | 结构化 JSON 输出、注册表一致性 |
| `tests/test_metrics.py` | 16 | — | 指标采集、token 核算、分阶段延迟 |

**集成测试：** `test_e2e.py` 跑 4 个多轮对话、12 轮，验证端到端行为——意图连续性、工具调用、上下文保持、升级门控。

`pytest -m "not integration"` 只跑单元测试，开发时用；提交前跑完整套件。

**测试发现的真实 bug：** 写 `test_skills.py` 时立刻发现 5 个 skill 的 `optional_tools` 里工具名少了 `_tool` 后缀（`"lookup_customer"` 应为 `"lookup_customer_tool"`）。`get_tools_for_skill()` 用 `set` 交集过滤，**静默丢弃不存在的名字**——这两个工具在 5 个场景里对 LLM 完全不可见。集成测试跑了几十次都没发现，因为 LLM 用 `search_product_info` 也能给出看似合理的回答。

**这是单元测试真正的价值：验证配置正确性，而不只是"输出看起来对"。** 同一次审查还发现 `skills.py` 的 system_prompt 里写着 "call search_kb"、"call lookup_pricing"——这些工具名在重命名后就不存在了，等于在指示 LLM 调用不存在的函数。这类问题集成测试永远发现不了。

### Q21c：工具返回值为什么改成 JSON？

**回答：** 之前每个工具返回给人看的文本：

```
Found 5 relevant results:
[1] radar | knowledge_base\payment\radar.md | relevance=0.851
Stripe Radar is an AI-powered fraud protection system...
```

下游要靠字符串切分拿来源：`line.split("|")[1].strip()`。三个地方在做这种解析——source 提取、product 提取、customer name 提取。任何格式微调都会静默破坏它们。重构时就踩到了：`run_agent()` 的 sources 提取是坏的，返回空数组，没人发现。

改成 JSON 后 [`app/tools.py:38`](app/tools.py#L38)，统一三种形态：

- `_ok(tool, **payload)` — 成功
- `_empty(tool, message, **payload)` — 成功但空（未知客户不是错误，`results: []` + 说明）
- `"ERROR: ..."` — 由管线异常处理器产生，工具自身不产生

`parse_tool_output()` 恢复成 dict，非 JSON 返回 `{"ok": False, "raw": ...}`。三处提取全改成读字段。

**副作用是好的：** E2E 测试中 12 轮全部带上来源引用，之前只有部分轮次有。

**为什么区分 `_empty` 和 `ERROR`？** LLM 对这两者应该有不同反应：`_empty` 说明"查到了，但没有数据"，LLM 应该如实告诉用户；`ERROR` 说明"查询失败了"，LLM 应该尝试别的工具。混在一起会让 LLM 把系统故障当成业务事实。

### Q21d：工具缓存怎么设计的？什么能缓存什么不能？

**回答：** [`app/tool_cache.py`](app/tool_cache.py)，会话级、TTL 有界的进程内缓存。

**键：** `f"{tool_name}:{sha256(json.dumps(args, sort_keys=True))[:16]}"`。`sort_keys` 让参数顺序无关——LLM 生成的 arguments JSON 键顺序不保证稳定，直接拿原始字符串做键会漏命中。工具名做前缀不拌进哈希，debug 时能直接看出是哪个工具。

**能缓存：** 5 个数据读取类工具，会话内数据不变。

**不能缓存：** `check_escalation_tool`。表面上它的 `query` 参数进了哈希，不同 query 天然不同键，缓存"安全"。但这里的边界画在**"读数据 vs 做决策"**上：升级判断依赖对话状态，任何一次让它变得上下文敏感的改动都会让缓存静默失效——这种 bug 极难发现。

**永不缓存：** `ERROR:` 开头的输出。缓存 15 分钟意味着一次瞬时的 Milvus 抖动变成一次会话级故障。ACT 里还额外加了 `if not is_error` 才 `put`，双保险。

**两级驱逐：**
- 条目级：50 条/会话，按 `created_at` 淘汰最老的。**命中不刷新 `created_at`**——绝对过期，不是滑动窗口，保证数据最多陈旧 15 分钟。
- 会话级：200 会话，按 `last_access` LRU。**命中刷新 `last_access`**——活跃会话不被踢。

两个维度管两件事：活跃会话保留，但活跃会话里的老数据仍会过期。

**实测：** 客户预加载 24.4ms → 0.8ms。

**但要诚实：** 单轮 20 秒里省 24ms 是 0.1%，对总延迟没意义。真正价值有三个——(1) `search_product_info` 命中时省的是 embedding API 调用 + ANN 检索，量级大得多；(2) 并发下的数据库压力；(3) **这个数字本身是正确性断言**——如果键不稳定，第二轮会是 24ms→24ms 而不是 24ms→0.8ms。

**已知缺陷：** 进程内（多 worker 各一份）、无主动失效、`_evict_stale_sessions()` 的"先算列表再删除"不是原子的（并发下理论上会 `KeyError`，实践未触发，但加锁成本很低）。

### Q21e：可观测性记录了什么？

**回答：** [`app/metrics.py`](app/metrics.py) 每轮写一行 `turn_metrics`：

| 字段组 | 内容 |
|---|---|
| Intent | scenario、method（keyword/keyword+context/llm）、confidence |
| Tools | 工具名数组、总次数、缓存命中数 |
| Loop | ReAct 迭代次数 |
| LLM | 调用次数、prompt tokens、completion tokens |
| Latency | 总延迟 + 分阶段（preload/intent/react_loop/synth/escalation） |
| Outcome | 是否升级、升级团队、错误信息 |

`save()` 整个包在 `try/except` 里——可观测性永远不能拖垮请求。

**之前答不了、现在能答的：**
- 意图分类多久回退一次 LLM？→ `intent_breakdown()` 的 `via_keyword`/`via_llm`
- 延迟花在哪？→ `latency_stages`（发现 SYNTH 占 60-70%，之前一直以为是检索慢）
- 缓存命中率？→ `summary()` 的 `cache_hit_rate`（实测 0.424）
- 典型查询几轮 ReAct？→ `avg_iterations`（实测 1.30，说明 `max_iterations=3` 的上限几乎不触发）

`GET /api/metrics?days=7` 暴露三个聚合 + `tool_cache.stats()`。

**一个真实的坑：** `tests/test_metrics.py` 的 `save()` 测试直接写生产 DB，污染了统计（20 行里有 2 行是测试数据）。正确做法是 fixture 里指向临时 DB。**当前没修**，属于已知债务。

---

## 八、设计决策与权衡

### Q22：关键词优先的意图分类 vs 始终用 LLM？

**回答：** 成本-延迟优化，且现在有实测支撑。

约 80% 的销售查询含明显关键词。实测 keyword 路径 **0.9ms**，LLM 路径 **1674ms**——1800 倍差距。token 成本：keyword 0，LLM 约 200 input + 50 output。

**0.6 阈值怎么来的** [`app/intent.py:25`](app/intent.py#L25)：置信度是 `min(matched_patterns / 3, 1.0)` [`app/intent.py:116`](app/intent.py#L116)。所以：
- 匹配 2 个关键词 = 0.67 ≥ 0.6 → 信任关键词
- 匹配 1 个关键词 = 0.33 < 0.6 → 调 LLM 确认

即"至少两个关键词共同指向同一场景才算可信"。

**这个阈值有数据支撑吗？没有。** 是经验初始化值。正确的校准方法：准备 100-200 条人工标注的查询，分别跑关键词和 LLM，在分歧集上分析——关键词漏判率和 LLM 误判率的交叉点就是最优阈值。`turn_metrics` 已经记录了 `intent_method` 和 `intent_confidence`，具备了做这件事的数据基础，但**还没做**。

**最具体的场景胜出** [`app/intent.py:106-116`](app/intent.py#L106)：多场景匹配时选匹配关键词最多的，而非第一个匹配的。天然倾向更具体的判断。

### Q23：为什么 Milvus 而不是 Chroma / Pinecone / FAISS？

| 因素 | Chroma | FAISS | Pinecone | Milvus（选择） |
|---|---|---|---|---|
| 标量过滤 | 基础 | 无原生支持 | 有 | 完整 expression language |
| 本地开发 | 简单 | 简单 | 需要云 | Milvus Lite 零依赖 |
| 生产迁移 | 需改代码 | 需改代码 | 云锁定 | Lite→Docker→Cloud，同一 API |
| 并发 | 单进程 | 无服务化 | 高 | Docker 模式支持 |

**关键因素：标量过滤是刚需。** KG 生成的 `product in [...] and access_level == "public"` 需要原生高效支持。Chroma 的元数据过滤是后加的，复杂 expression 支持有限。FAISS 没有服务化能力。Pinecone 本地开发必须连云。

**反方观点：** 278 个 chunk 的规模下，其实 FAISS + 手写 Python 过滤完全够用，甚至更快（没有进程间通信）。选 Milvus 是为**迁移路径**付的溢价——如果确定不会扩展，这个选择是过度工程。

### Q24：为什么 text-embedding-3-small 而不是 large 或本地模型？

| 模型 | 维度 | 成本 | 适用 |
|---|---|---|---|
| text-embedding-3-small | 1536 | $0.02/1M | 中等语料（< 10K chunks） |
| text-embedding-3-large | 3072 | $0.13/1M | 大规模语料 |
| BGE-large-zh | 1024 | 免费 | 中文、需本地部署 |

278 个 chunk 的规模下，small 和 large 的检索精度差异可忽略（约 1-2%），成本差 6.5 倍。切换只需改常量 [`app/milvus_retriever.py:35`](app/milvus_retriever.py#L35) 和 [`app/milvus_loader.py:287`](app/milvus_loader.py#L287)，但**要重建整个 collection**（维度变了），不是零成本的。

### Q25：OpenAI function calling 和传统 prompt engineering 的本质区别？

**回答：** 传统方式把工具描述塞进 system prompt，让 LLM 从文本里"猜"该输出什么格式，然后用正则/JSON 解析去抠。Function calling 让 LLM 在独立的 `tool_calls` 字段返回结构化的函数名和参数——**格式由 API 保证，不需要解析容错**。

底层其实还是 prompt——OpenAI 把 tool schema 序列化进上下文，并用训练让模型输出特定的结构。但对使用者，它把"格式正确性"从应用层的责任变成了 API 的责任。

**三层关系：**
- **function calling** = LLM 精确调用函数的能力
- **ReAct Loop** (`_run_pipeline`) = 管理多步调用之间的状态和终止条件
- **SkillConfig** = 为不同场景注入不同的 system prompt 和工具白名单（决定哪些函数进 schema）

---

## 九、大厂 Agent 面试深挖

> 这一节针对国内大厂 LLM 应用 / Agent 开发岗常见的追问。原则：能答的用本项目实测数据答，没做的直说没做，并给出会怎么做。

### Q40：RAG 的检索效果怎么评估？你这个项目测了吗？

**回答：先说结论：本项目没有做定量的检索评估，这是最大的短板。**

标准做法是三层指标：

| 层级 | 指标 | 含义 |
|---|---|---|
| 检索 | Recall@k | top-k 里包含正确文档的比例——**RAG 的天花板**，检索不到后面全白搭 |
| 检索 | MRR / NDCG@k | 正确文档排得够不够靠前，影响 LLM 是否注意到 |
| 生成 | Faithfulness | 回答有多少比例能被检索到的内容支撑（反幻觉） |
| 生成 | Answer Relevance | 回答是否切题 |

**为什么本项目没做：** 没有标注数据集。要做需要人工构造 100-200 条 `(query, 相关文档 ID 列表)` 的 golden set。

**具备的基础：** 21 篇文档、278 个 chunk，规模小到可以人工标注。`turn_metrics` 已经记录了每轮的 query 和工具调用。

**会怎么做：**
1. 从 `sales_interactions` 的 97 条真实查询里抽样，人工标注每条应该命中哪些文档
2. 跑两组对照：`use_kg_filter=True` vs `False`，比 Recall@5
3. 这直接验证了 Q3 里"KG 提升精度"的说法——**当前这个说法是靠逻辑推演的，没有数据。** 面试时我会明确这样讲。

**KG 过滤的风险也能被这个实验量化：** 如果 KG 漏了一条边，正确文档会被过滤掉，Recall 反而下降。有数据才知道过滤到底是净收益还是净损失。

### Q41：为什么不做混合检索（BM25 + 向量）？怎么融合？

**回答：本项目是纯向量 + 标量过滤，没有 BM25。**

**混合检索解决的问题：** 向量检索擅长语义相似（"如何防欺诈" ↔ "Radar fraud detection"），但对**精确匹配**很弱——产品名、错误码、API 字段名、版本号。用户问 "PaymentIntent 的 confirm 参数"，向量检索可能返回一堆讲支付流程的泛泛内容，BM25 反而能精确命中。

**本项目的替代方案：** KG 的产品别名表 [`app/kg_retriever.py:43`](app/kg_retriever.py#L43) 做了部分精确匹配的活——把 "radar"、"payment link"、"ASC 606" 映射到产品 ID，再转成标量过滤。这是**用结构化知识替代 BM25 的稀疏匹配**，在产品名封闭、数量有限（16 个产品）的场景下够用，但对文档里的长尾术语无能为力。

**要做的话怎么融合——RRF（Reciprocal Rank Fusion）：**

```python
score(d) = Σ_over_retrievers  1 / (k + rank_i(d))     # k 通常取 60
```

RRF 只用排名不用分数，天然规避了"BM25 分数和余弦相似度量纲不同"的归一化难题。这是工业界默认选择。

**Milvus 2.4+ 原生支持 hybrid search**（稀疏向量 + 稠密向量 + `RRFRanker`），改造成本不高：入库时多存一列稀疏向量（BM25 或 SPLADE），检索时用 `AnnSearchRequest` 双路召回。**当前没做，因为没有评估集，无法证明它带来了改进。**

### Q42：要不要加 rerank？

**回答：当前没有 rerank。**

**标准两阶段架构：** 向量召回 top-50（快，双塔模型，query 和 doc 独立编码）→ Cross-Encoder 精排 top-5（慢，query 和 doc 拼一起过一遍模型，能建模细粒度交互）。

**本项目为什么没加：**

1. **候选集本来就小。** KG 过滤后只剩约 30 个 chunk，top-5 是从 30 里选，rerank 的边际收益有限。rerank 的价值在"从 100+ 候选里精选"。
2. **延迟预算。** 实测 SYNTH 已经占 6-11 秒，再加 200-500ms 的 rerank 收益/成本比不划算。真要优化延迟，先并发化那两个 SYNTH 调用。
3. **没有评估集，无法验证。**

**什么情况下必须加：** 文档量上到数千篇、KG 过滤失效（长尾查询匹配不到产品）、或者观测到"正确答案在 top-20 但不在 top-5"——这正是 NDCG 能量化的问题。

### Q43：Query 改写 / HyDE 用了吗？

**回答：用了一种轻量形式，但不是 LLM 改写。**

`kg.expand(query)` [`app/kg_retriever.py:95`](app/kg_retriever.py#L95) 做的就是查询扩展——只不过扩展的是**元数据过滤条件**而不是查询文本本身。原始 query 文本原样送去 embedding，扩展的产物是 `product in [...]` 过滤器。

**三种主流方案的对比：**

| 方案 | 做法 | 代价 |
|---|---|---|
| LLM query rewrite | 让 LLM 把口语化问题改写成检索友好的表述 | +1 次 LLM 调用（约 500ms） |
| HyDE | 让 LLM 先编一个"假想答案"，用它的 embedding 检索 | +1 次 LLM 调用，且假想答案可能带错误方向 |
| Multi-query | 生成 3-5 个查询变体分别检索再融合 | +1 次 LLM 调用 + N 次检索 |
| **KG 扩展（本项目）** | 关键词匹配 + 图遍历生成过滤器 | ~1ms，零 token |

**本项目最需要 query rewrite 的地方是多轮指代。** "那定价呢？"——这句话直接 embedding 检索毫无意义。当前是靠 intent 层的上下文继承解决的（Q35），但**检索层没有解决**：`search_product_info` 收到的还是 LLM 自己组织的 query 字符串。实际上 LLM 在 THINK 阶段会自然地把上下文融进工具参数（它看得到对话历史），这算是"LLM 隐式做了 query rewrite"——但不可控、不可观测。

**改进方向：** 在 ACT 之前，如果 query 被判定为模糊（`_is_ambiguous()` 已有），用上一轮的 topic 显式补全工具参数。这比引入完整的 rewrite 链路成本低得多。

### Q44：向量索引怎么选？HNSW 和 IVF 的区别？

**回答：本项目用的是 Milvus 的 `AUTOINDEX`** [`app/milvus_loader.py:222`](app/milvus_loader.py#L222)，把选择权交给了 Milvus——在 Milvus Lite 下它实际落到暴力检索或轻量 HNSW，因为 278 个向量根本不需要 ANN。

**这是有意的：** 278 个向量做暴力搜索是 278 次 1536 维点积，微秒级。任何 ANN 索引在这个规模下都是负优化（构建开销 + 精度损失换不来速度）。

**规模上来后要怎么选：**

| 索引 | 原理 | 构建 | 查询 | 内存 | 适用 |
|---|---|---|---|---|---|
| FLAT | 暴力 | 无 | O(n) | 低 | < 10K，要 100% 召回 |
| IVF_FLAT | 聚类分桶，只搜最近的 nprobe 个桶 | 快 | 中 | 中 | 10K-1M |
| HNSW | 多层跳表图，贪心搜索 | 慢 | 快 | **高** | 高 QPS、低延迟 |
| IVF_PQ | IVF + 乘积量化压缩 | 中 | 快 | **低** | 内存受限的超大规模 |

**关键参数：**
- IVF：`nlist`（桶数，经验值 `4*sqrt(n)`）、`nprobe`（查询时搜几个桶，**召回/延迟的旋钮**）
- HNSW：`M`（每层邻居数，越大越准越占内存）、`efConstruction`（构建质量）、`ef`（查询时候选集大小，**运行时旋钮**）

**实践要点：** `nprobe` 和 `ef` 是唯二可以在**不重建索引**的前提下调节召回率的参数。上线前应该扫一遍这两个参数，画出"召回率 vs 延迟"曲线再定值。

### Q45：ReAct 和 Plan-and-Execute、Reflexion 怎么选？

**回答：本项目用 ReAct，因为任务的步数少且步骤依赖数据。**

| 范式 | 机制 | 适合 | 不适合 |
|---|---|---|---|
| **ReAct** | 每步都重新决策 | 步数少（1-5）、下一步依赖上一步结果 | 长任务（每步都要全量上下文，token 爆炸） |
| **Plan-and-Execute** | 先出完整计划，再逐步执行 | 步数多、步骤相对独立、可并行 | 中途环境变化时计划失效 |
| **Reflexion** | 执行后自我批判，失败则重试 | 有明确成功/失败信号（代码能否跑通） | 没有客观验证信号时，自我批判就是自我幻觉 |

**本项目的判断依据：**

- `avg_iterations = 1.30`，`max_iterations ≤ 3`。**步数这么少，Plan 的开销（额外一次 LLM 调用出计划）比它省的还多。**
- 步骤强依赖：先查到客户年交易额是 $5M，才知道要不要去查自定义定价门槛。Plan-and-Execute 在出计划时并不知道交易额。
- **没有客观成功信号。** 销售回答的好坏无法自动判定，Reflexion 的"自我批判"在这里只会产生看似深刻实则无根据的修改。

**什么时候该换：** 如果加入"生成完整销售提案"这类任务——需要查客户、查产品、查定价、查竞品、生成 PPT 大纲，步骤 8-10 步且大部分独立——那时 Plan-and-Execute 加并行执行会明显更优。

### Q46：怎么防止 Agent 死循环？

**回答：本项目有四道防线：**

1. **硬上限** `skill.max_iterations`（0-3）[`app/graph.py:323`](app/graph.py#L323)。这是最后一道保底，任何情况下循环不会超过它。
2. **连续错误熔断** [`app/graph.py:435`](app/graph.py#L435)：尾部连续 2 次 `is_error` → 强制合成。防的是"工具一直失败但 LLM 一直重试同一个"。
3. **提示层约束**：system prompt 明确写 "Call each tool you need ONCE — do not repeat the same call" [`app/graph.py:676`](app/graph.py#L676)。
4. **工具缓存的副作用**：重复调用同参数工具时直接返回缓存，虽然不阻止循环，但让重复循环的成本降到近零，且返回完全相同的结果——LLM 看到一模一样的输出更容易判断"这条路没用"。

**没做但业界常见的：**
- **状态哈希去重**：把 `(tool_name, args)` 序列记下来，检测到 A→B→A→B 的振荡模式直接中断。当前靠 `max_iterations=3` 挡住了，规模上去要加。
- **预算约束**：按 token 或耗时熔断，而不只是按轮数。一轮 9000 token 和一轮 500 token 的成本差 18 倍，只数轮数是不够的。

### Q47：Agent 的效果怎么评估？

**回答：本项目只有端到端的行为断言，没有量化评估。**

`test_e2e.py` 跑 4 个多轮对话共 12 轮，断言的是：意图分类正确、调用了预期的工具、上下文没丢、升级门控符合预期。这是**回归测试**不是**效果评估**——它能防止改坏，不能告诉你现在多好。

**完整的 Agent 评估应该分三层：**

| 层级 | 评什么 | 怎么评 |
|---|---|---|
| Step-level | 每一步的工具选择对不对、参数对不对 | 标注 golden trajectory，比对工具序列 |
| Outcome-level | 最终答案对不对 | LLM-as-judge 或人工标注 |
| Trajectory-level | 路径是否高效（有没有多余步骤） | 比较实际步数 vs 最优步数 |

**本项目有价值的地方：`turn_metrics` 已经把 trajectory 存下来了**——`tools_called` 是完整的工具调用序列，`iterations` 是步数。有了这个，加一个标注集就能立刻跑 step-level 评估。

**LLM-as-judge 的坑（面试常问）：**
- **位置偏见**：成对比较时偏好第一个 → 要交换顺序跑两遍
- **长度偏见**：偏好更长的回答 → 要在 rubric 里显式约束
- **自我偏好**：GPT 评 GPT 的输出分数偏高 → 用不同家族的模型做裁判
- **裁判本身要被评估**：先用人工标注的一小批数据验证裁判和人的一致性（Cohen's kappa），一致性不够的裁判结果没有意义

### Q48：多 Agent 架构考虑过吗？

**回答：考虑过，明确否决了。**

本项目的 13 个场景看起来很像"13 个专家 Agent + 一个路由 Agent"的经典 multi-agent 结构。实际选择是**单 Agent + 配置化 Skill**。

**理由：**

1. **场景之间共享全部工具。** 13 个场景用的是同一个工具池的不同子集，没有任何场景需要独占的能力。多 Agent 的价值在于"不同 Agent 有本质不同的能力/权限"，这里不成立。
2. **多意图查询会打架。** 用户同时问 Billing 和 SOC 2 时，multi-agent 要么串行调两个 Agent（延迟翻倍）要么并行后再合并（合并本身又是一次 LLM 调用）。当前方案是把副意图的领域引导注入同一个 prompt [`app/graph.py:159`](app/graph.py#L159)，一次搞定。
3. **状态同步是纯开销。** 客户档案、对话历史、升级判断都是全局状态。多 Agent 之间传递这些状态只会引入序列化成本和不一致风险。

**什么时候多 Agent 才划算：** 当子任务需要**不同的模型**（一个用便宜模型做分类、一个用强模型做推理）、**不同的权限边界**（一个能写数据库、一个只读）、或者**能真正并行**（互不依赖的调研任务）。本项目三条都不满足。

### Q49：怎么控制成本？

**回答：本项目做了三件事，实测每轮约 $0.0008。**

已做的：

1. **关键词优先的意图分类** — 约 80% 查询不调 LLM，省一次完整往返
2. **out_of_scope 快速通道** — 无关查询 3ms 拦截，**零 token**
3. **工具结果缓存** — 省的是 embedding API 调用和 SQL，不是 LLM token

**没做但影响更大的：**

1. **Prompt Caching。** OpenAI 对 1024 token 以上的重复前缀自动打 50% 折扣。本项目的 system prompt + tool schemas 每轮都一样，是天然的缓存前缀。但**当前 THINK 每轮重建 messages 时，system prompt 在最前面是稳定的，其实已经能吃到部分折扣**——只是从没验证过。`response.usage` 里有 `prompt_tokens_details.cached_tokens`，加一行埋点就能量化。

2. **模型分级路由。** 意图分类、escalation 判断这类简单分类任务用 gpt-4o-mini 已经是最便宜的了；但 SYNTH 的两次调用可以考虑：internal_answer 给销售看，可以用更强的模型；client_ready 是改写任务，可以用更小的。当前全用 gpt-4o-mini，没有分级。

3. **减少 SYNTH 调用数。** 两次 LLM 调用生成两份回答——其实可以一次调用返回结构化的两个字段。省一次往返，但会牺牲两份回答各自的 temperature 控制（internal 要 0.2 求准确，client 要 0.4 求自然）。这是个真实的取舍，不是纯优化。

**成本结构的关键认知：** 实测 `tokens_in 64708 / tokens_out 9873`，**输入是输出的 6.5 倍**。虽然输出单价是输入的 4 倍，但输入总量大，两者成本接近。而输入token 大头来自 THINK 每轮重建完整消息列表——优化空间在这里，不在输出。

### Q50：怎么检测和降低幻觉？

**回答：本项目做了三层约束，但没有自动检测。**

**已做的约束：**

1. **强制 grounding 提示** — system prompt 写明 "Prefer tools over memory for specific facts, rates, and policies" [`app/graph.py:675`](app/graph.py#L675)，首轮还会追加 "every factual claim needs a source"。
2. **工具白名单** — LLM 看不到的工具就调不到，减少了"用错工具产生无关内容"这类污染。
3. **来源可溯** — 结构化 JSON 输出让 `sources` 字段能准确指回具体的 `knowledge_base/...md` 文件。销售可以人工核对。
4. **场景级的显式警告** — `saas_billing`、`tax_compliance`、`pricing_negotiation`、`security_compliance` 四个 skill 的 system_prompt 里明确写着 "Your training data may be outdated. Do NOT quote from memory."——因为这四类信息（定价、税务、合规流程）是**变化最快且答错代价最高**的。

**没做的：**

- **自动 faithfulness 检测。** 标准做法是把生成的回答拆成原子声明，逐条去检索到的 chunk 里找支撑，算支撑比例。可以用 NLI 模型或 LLM-as-judge。
- **拒答机制。** 当前检索结果为空时，`_empty()` 会告诉 LLM "没找到"，但没有硬性阻止 LLM 继续用训练知识回答。更严格的做法是：`search_product_info` 返回空且该场景 `required_tools` 非空时，直接返回"知识库中没有这个信息"的固定话术。

**最诚实的一点：** 这个系统的输出是给销售看的，销售会二次判断——这是当前不做自动检测的实际理由。如果改成直接面向客户，faithfulness 检测就是必须项。

### Q51：线上出了 badcase 怎么闭环？

**回答：数据基础有了，闭环没建。**

**现有的数据：**
- `sales_interactions` — 每轮的 query、detected_intent、mentioned_products
- `turn_metrics` — 完整的执行轨迹：意图路径、工具序列、迭代数、token、分阶段延迟、错误
- `session_memory` — 完整对话历史

**能直接跑的分析（不需要新开发）：**
```sql
-- 哪些意图最常回退 LLM？说明关键词覆盖不足
SELECT intent, SUM(intent_method='llm')*1.0/COUNT(*) FROM turn_metrics GROUP BY intent;

-- 哪些轮次跑满了迭代上限？说明信息收集困难
SELECT * FROM turn_metrics WHERE iterations >= 3;

-- 哪些轮次一个工具都没调？说明 LLM 在凭记忆答
SELECT * FROM turn_metrics WHERE tool_calls = 0 AND intent != 'out_of_scope';
```

最后一条特别重要——**"零工具调用"是幻觉风险的最强代理指标**，不需要人工标注就能筛出来。

**缺的部分：**
1. **用户反馈入口。** 前端没有"有用/无用"按钮。这是最低成本的改动，也是整个闭环的起点。
2. **badcase → 知识库的路径。** 现在发现某个问题答不好，要手工去写 markdown、手工更新 KG YAML、手工重跑 `milvus_loader --force`。三步都是人肉的。
3. **回归防护。** 修好一个 badcase 后没有机制保证它不会退化——应该把每个 badcase 固化成 `test_e2e.py` 里的一个用例。

**优先级排序：** 先加反馈按钮（1 天），再把差评样本自动导出成待标注队列（1 天），最后才考虑自动化知识库更新（风险高，容易引入错误知识）。

### Q52：temperature=0 为什么输出还是不稳定？

**回答：** `temperature=0` 只是让采样退化为取概率最大的 token（greedy decoding），**不保证确定性**。三个原因：

1. **浮点非确定性。** GPU 上的并行归约（reduction）顺序不固定，导致 logits 有极小的数值差异。当两个候选 token 概率极接近时，这点差异会翻转 argmax 的结果，然后误差沿序列放大。
2. **MoE 模型的批次干扰。** 混合专家模型的路由可能受同批次其他请求影响（这一条在闭源模型上无法验证，但是业界公认的解释之一）。
3. **服务端的模型版本漂移。** `gpt-4o-mini` 是滚动别名，OpenAI 可以在不改名的情况下更新底层权重。

**本项目受影响的地方：** intent 分类和 escalation 判断都用 `temperature=0`，绝大多数情况稳定，但**边界样本会翻转**——置信度接近 0.6 阈值的查询，可能这次走关键词下次走 LLM。

**工程上怎么应对：**
- 用 `seed` 参数（OpenAI 支持）+ 检查响应的 `system_fingerprint`，fingerprint 变了说明后端变了
- **不要让测试断言依赖 LLM 的具体输出。** 本项目的 198 个单元测试全部不调 LLM，就是这个原因——测的是关键词匹配、token 预算、缓存键这些确定性逻辑
- 边界样本用规则兜底，而不是指望 LLM 稳定

### Q53：流式输出的 TTFT 怎么优化？

**回答：本项目的"流式"是阶段级的，不是 token 级的——这是一个重要区别。**

`stream_agent()` 推送的是 pipeline 事件（intent / skill / think / act / observe / synth / escalation / done），每个阶段完成后整体推一次。**SYNTH 生成的文本不是逐 token 流出来的**——`_call_llm_with_retry()` 没有开 `stream=True`。

**所以用户体验是：** 进度条式的反馈很快（intent 事件在 1ms-1.7s 内到达），但**最终答案要等 6-11 秒的 SYNTH 结束才一次性出现**。

**三个优化方向，按性价比排序：**

1. **两次 SYNTH 并发。** internal 和 client 互相独立，串行跑 6-11 秒。用 `asyncio.gather` 并发能砍掉约 40% 总延迟。**改动最小、收益最大，是当前第一优先级。**
2. **client_ready 开 token 流式。** 用户真正在等的是这份回答。`stream=True` 后逐 token 推送，TTFT 从"整个 SYNTH 结束"降到"SYNTH 第一个 token"。代价是要改 SSE 事件格式（加一个 `token` 事件类型）和前端的增量渲染。
3. **乐观渲染。** 在 THINK 决定要调工具时就先把"正在查询知识库..."推给前端。当前的 `think` 事件已经带了 `tool_name`，前端做文案映射就行，零后端改动。

**为什么当初没做 token 流式：** 阶段级事件对这个产品更有价值——销售想看到 agent"在查什么"，这是信任建立的过程。纯 token 流式反而丢失了这个信息。理想方案是两者都有：阶段事件 + 最终回答的 token 流。

### Q54：如果 QPS 涨到 100，这套架构哪里先崩？

**回答：按崩溃顺序：**

1. **Milvus Lite 的文件锁**（QPS ~5 就开始排队）。`search()` 被完全串行化。这是第一个崩的，也是最容易修的——换 Docker，改一行 URI。
2. **SQLite 写入**（QPS ~20-50）。每轮要写 `session_memory` + `sales_interactions` + `turn_metrics` 三张表。WAL 支持并发读但写是串行的，`busy_timeout=5000` 会让请求排队 5 秒后失败。修法：三个写操作合并成一个事务、或者把 metrics 写入改成异步队列。
3. **单连接对象的竞争**（同上量级）。`get_connection()` 返回全局单例 [`app/database.py:27`](app/database.py#L27)，所有线程共用。应该改成 `threading.local()` 或连接池。
4. **OpenAI 速率限制**（取决于账户 tier）。QPS 100 × 每轮 4-6 次 LLM 调用 = 400-600 RPM 的下游请求。`_call_llm_with_retry` 有 429 重试，但重试会加剧拥塞。需要在入口做令牌桶限流，而不是靠下游重试。
5. **工具缓存的进程内特性**（多 worker 时命中率衰减，但不会崩）。

**优先级判断：** 1 和 2 是硬故障（请求失败），3 是正确性风险，4 需要架构级的限流设计。前三个加起来大概两天工作量。

### Q55：这个项目你觉得最大的技术短板是什么？

**回答：三个，按严重程度排。**

1. **没有检索质量的量化评估。** 整个 KG-enhanced RAG 的核心卖点——"KG 过滤提升检索精度"——是靠逻辑推演成立的，**没有一个数字支撑**。它甚至可能是负收益（KG 漏边导致召回下降）。这是最应该先补的。

2. **SYNTH 的两次 LLM 调用串行。** 占了总延迟的 60-70%，而且是纯粹的浪费——两次调用之间没有任何依赖。这是"有明确解法但还没做"的债。

3. **意图分类阈值没有数据校准。** 0.6 是拍的。`turn_metrics` 现在记录了 `intent_method` 和 `intent_confidence`，具备了校准的数据基础，但需要一个标注集。

**共同点是：这三个都是"缺数据"而不是"缺设计"。** 项目在架构层面（单管线、配置化 Skill、结构化工具输出、缓存、可观测性）已经比较完整，下一步的瓶颈全部在评估侧。这也是我做完可观测性之后最直接的体感——埋点让延迟分布从"我以为 2-4 秒"变成"实测 9.8 秒"，那么检索质量大概率也存在类似量级的认知偏差。

---

## 十、进阶追问

### Q26：面试时按什么顺序打开文件讲解？

| 顺序 | 文件 | 讲解重点 |
|---|---|---|
| 1 | `knowledge_base/knowledge_graph.yaml` | 数据层：80 节点、150 三元组，8 种实体类型、9 种关系 |
| 2 | `app/kg_builder.py:26-141` | YAML → networkx，五个 lookup 方法 |
| 3 | `app/kg_retriever.py:95-217` | `expand()` 六步 + `build_filter_expr()` |
| 4 | `app/milvus_loader.py:244-339` | 切分 → KG 增强 → embed → 入库 |
| 5 | `app/milvus_retriever.py:106-188` | KG 扩展 → filter 拼接 → embed → search |
| 6 | `app/skills.py:13-44` | SkillConfig 8 字段 + 14 条注册表 |
| 7 | `app/tools.py:38-114` | JSON 输出契约 + `search_product_info` 实现 |
| 8 | `app/intent.py:71-314` | 关键词 → context boost → 快速通道 → LLM → 安全网 |
| 9 | `app/escalation.py:81-224` | 双重门控 + 上下文 LLM 层 |
| 10 | `app/context.py:98-176` | 三层窗口 + 二分截断 |
| 11 | `app/graph.py:206-599` | `_run_pipeline()`：全链路 |
| 12 | `app/tool_cache.py` | 缓存键设计 + 两级驱逐 |
| 13 | `app/metrics.py` | 埋点字段 + 三个聚合查询 |
| 14 | `app/main.py:25-139` | 生命周期 + 6 个端点 |

### Q27："如果重新做，你会有什么不同的设计？"

**回答：** 分两类——已经改掉的，和还没改的。

**已经改掉的（当初设计不当，后来重构）：**

1. **不该一上来就用 LangGraph。** `StateGraph` 的阻塞式 `invoke()` 和流式输出天然冲突，最后导致两套实现漂移。现在是一个生成器 + 两个薄封装，反而更简单。**判断标准：先确认框架假设的执行模型和你的需求一致。**

2. **工具输出不该是给人看的格式化字符串。** 三处下游代码靠字符串切分取字段，其中一处静默坏了很久。现在全是 JSON。

3. **不该用增量累加管理 messages。** LangGraph 的 `operator.add` reducer 导致 tool_call 配对断裂。现在每轮从零重建。

**还没改的（明确的下一步）：**

4. **先建评估集，再谈优化。** 整个项目的检索侧优化都是盲的。如果重来，我会在写第一行检索代码之前先标注 50 条 golden query。

5. **SYNTH 两次调用并发化。** 占 60-70% 延迟的纯浪费。

6. **KG 的自动构建。** 150 条三元组是手写的，21 篇文档的规模还行，扩展到数百篇必须用 LLM 做实体抽取 + 关系抽取，并配上人工审核界面。

7. **权限控制统一到一层。** 现在 Milvus 走 `access_level` 过滤，`lookup_pricing_tool` 走代码里手工切段落，两套机制。应该统一到工具层的 access control。

8. **用户反馈闭环。** 前端加"有用/无用"按钮是 1 天的事，但它是整个数据飞轮的起点。

### Q28："这个系统最容易出 bug 的地方是哪里？"

**回答：** 按实际踩坑频率排序。

1. **配置和代码的名字不一致。** 这是本项目出现最多次的 bug 类型：`optional_tools` 里工具名少 `_tool` 后缀（5 处）、system_prompt 里写 `search_kb` 而实际工具叫 `search_product_info`（6 处）、DB 存 `'Security'` 而 LLM 传 `"security"`（1 处）。**共同特征是全部静默失败**——工具被过滤掉、LLM 找不到函数、SQL 查不到——但系统照常返回看似合理的答案。防线只有单元测试（断言注册表一致性）和大小写归一化。

2. **LLM 返回格式不一致。** 多处 `json.loads(llm_response)`，LLM 可能返回 markdown 包裹的 JSON、多余换行、错误字段名。已做 `removeprefix("```json")` 清理 + 解析失败回退，但边界情况仍在。

3. **tool_call_id 配对。** 重建消息时 `tool_call_id` 必须与 `assistant.tool_calls[0].id` 完全一致，缺 `"type": "function"` 也会 400。开发期反复出现过。

4. **KG YAML 和知识库 .md 的一致性。** 两套手工维护的数据。新增文档但忘记更新 YAML 里的 product 实体 → 该文档的 chunk 缺 KG 增强字段 → 检索时永远匹配不到产品过滤器。**这个 bug 会让文档"从检索中消失"，且完全没有报错。**

5. **同 session 的并发写入。** 用户快速双击发送，两个请求同时 `save_session`，UPSERT 会竞态。SQLite 串行写不会丢数据，但 turns 顺序可能意外。

### Q29："tool whitelist 降低幻觉——能举个没有 whitelist 会出错的例子吗？"

**回答：先纠正一个可能的误解——whitelist 在本项目里比想象的宽松。**

`marketplace` 场景实际暴露 **5 个**工具（`search_product_info` + `lookup_customer_tool` + `lookup_product_usage_tool` + `lookup_policy_tool` + `lookup_pricing_tool`），6 个里只挡掉了 `check_escalation_tool`。

**真正收紧的是这些场景：**
- `global_expansion`：只有 2 个（`search_product_info` + `lookup_pricing_tool`）
- `tax_compliance` / `security_compliance` / `pricing_negotiation`：只有 2 个
- `escalation_request` / `out_of_scope`：**0 个**，连循环都不进

**具体的错误例子（global_expansion）：** 用户问"我们要拓展到东南亚，支持哪些本地支付方式？"。如果全部工具可见，LLM 很可能去调 `lookup_customer_tool` 和 `lookup_policy_tool`——因为"拓展"听起来像需要客户背景，"合规"听起来像需要政策。这两次调用各消耗一轮迭代和一次 LLM 往返，返回的内容和支付方式毫无关系，还占据了 SYNTH 的上下文预算，稀释了真正有用的知识库检索结果。whitelist 让这两个工具根本不出现在 function schema 里。

**`escalation_request` 是最强的例子。** `max_iterations=0` + 零工具，意味着用户说"帮我转人工"时，agent 不会去搜知识库、不会查客户档案，直接进 SYNTH 用对话历史生成一段交接摘要。**如果不做这个限制**，LLM 面对"connect me to someone"多半会去 `search_product_info("connect")`——把"转接"理解成 Stripe Connect 产品。这不是假想，是实际发生过的 bug。

### Q30："intent 分类的 0.6 阈值是怎么定的？有数据支撑吗？"

**回答：没有数据支撑，是经验值。** 见 Q22 的推导（`min(matched/3, 1.0)`，0.6 等价于"至少两个关键词"）和校准方法。

**现在比当初多了一件事：** `turn_metrics` 记录了每轮的 `intent_method` 和 `intent_confidence`，所以可以先做一件不需要标注的事——统计置信度分布，看有多少查询落在 0.5-0.7 这个敏感带里。如果这个区间的查询只占 5%，阈值调整的影响就很小，不值得投入标注成本；如果占 30%，就必须认真校准。**这是"用观测数据决定要不要做实验"，比直接上标注更省力。**

### Q31："如果有 100 个场景 Skill 而不是 13 个，这个设计还能工作吗？"

**回答：能，但有三处要改。**

1. **意图分类的 LLM prompt 会爆。** 关键词匹配的 O(n×m) 遍历（13 场景 × 95 关键词 ≈ 1ms）线性增长到 ~8ms，可接受。但 LLM fallback 的 prompt 要列出 100 个场景名，token 成本和分类准确率都会劣化——**选项越多，LLM 分类越不准**。改法：两级分类，先分到 8-10 个大类，再在类内细分。

2. **SkillConfig 的组织。** 当前单个 390 行的 `skills.py`。100 个场景应该改成目录扫描——`skills/*.yaml`，`SKILL_REGISTRY` 在启动时加载。`SkillConfig` 本身是通用的，只改加载方式。

3. **关键词冲突会显著增加。** 13 个场景时"最具体的胜出"策略够用；100 个场景时关键词大量重叠，需要引入 IDF 加权（罕见关键词权重更高）或者干脆换成一个小的分类模型。

**不需要改的：** ReAct 循环、工具层、缓存、升级门控——它们都不感知场景数量。这正是"Skill 作为配置而非运行时"的价值：场景数是数据规模问题，不是架构问题。

### Q32："请解释 `_parse_frontmatter` 中 `in_frontmatter` 状态机的作用"

**回答：** [`app/milvus_loader.py:87`](app/milvus_loader.py#L87) 是两状态解析器。

**状态 0（标题区）：** 跳过 `# Stripe Checkout` 这类标题行、跳过空行。

**状态 1（元数据区）：** 遇到首个 `Key: Value` 行 → `in_frontmatter = True`。继续解析后续 `Key: Value`。遇到 `#` 开头、`-` 开头、`**` 开头、或不匹配 `Key: Value` 的行 → `break`。

**为什么需要这个标记？** 因为 `#` 在文档里出现两次且语义不同：开头的 `# 标题` 应该被**跳过**，正文的 `## Summary` 应该**终止解析**。只看 `line.startswith("#")` 无法区分这两者。`in_frontmatter` 提供了"我现在在哪个区"的上下文——同样的 `#` 行，在状态 0 是 `continue`，在状态 1 是 `break`。

**这是典型的"用状态区分同形输入"的场景**，也是最初那个 `if not line: break` bug 的根源：作者假设空行是分隔符，但实际文档格式是 `# 标题 → 空行 → Key: Value`，空行出现在元数据**之前**。

---

## 十一、多轮对话与交互

### Q35："那定价呢"——intent 怎么知道"那"指的是 Connect 还是 Billing？

**回答：** 四个机制协同。

1. **上下文注入** [`app/graph.py:714`](app/graph.py#L714)：`_build_context_hint()` 从 session turns 提取 `previous_scenario`（用 KG 关键词反推上一轮助手回复属于哪个场景）、`previous_topic`（上一条用户消息）、`summary`、`turns`。session 在 intent 之前加载，保证 hint 可用。

2. **关键词路径的 context boost** [`app/intent.py:118`](app/intent.py#L118)：当前 query 判定为模糊 **且** 上一轮 scenario 在当前候选中 → 加 0.15 置信度。处理"匹配到多个场景，但上下文指向上一轮那个"。

3. **超短跟进的直接继承** [`app/intent.py:177`](app/intent.py#L177)：query ≤ 2 个词（"yes"、"tell me more"）→ 直接继承上一轮场景，**完全跳过 LLM**。这个阈值最初设的是 3，后来降到 2——因为 "what about pricing?"（3 词）应该走正常分类，用户确实在切换话题。

4. **LLM 路径的 context block** [`app/intent.py:202`](app/intent.py#L202)：prompt 里注入 "Previous scenario: saas_billing. If this is a follow-up referencing the previous topic, classify it as the SAME scenario. Only switch if the user explicitly changes the topic."

**模糊判定** [`app/intent.py:42`](app/intent.py#L42)：≤ 5 个词 **或**含代词（it/that/this/they/them/those/these）。不模糊的查询（"Stripe Connect marketplace seller onboarding"）不受 context boost 影响——用户明确提新产品时，上下文不该阻止场景切换。

**"那定价呢"（4 个词）的实际路径：** 不满足 ≤2 词的超短规则；"定价" 会匹配到 `pricing_negotiation` 关键词，但只匹配 1 个 → 置信度 0.33 < 0.6 → 判定为模糊（≤5 词）→ 如果上一轮是 `pricing_negotiation` 则 boost 到 0.48，仍不够 → 走 LLM，由 context block 决定。

### Q37："今天天气怎么样"——Agent 怎么处理？

**回答：** 两层拦截，实测 **3ms、零 token**。

**第一层 — 关键词快速通道** [`app/intent.py:165`](app/intent.py#L165)：KG 匹配到 0 个 scenario **且** 查询不含 40 个 Stripe 信号词中的任何一个 **且** 无历史 **且** 无客户档案 → 直接 `out_of_scope`，confidence 0.05。

四个条件是 `and`，缺一不可。后两个是防误伤：多轮对话中的"yes"没有关键词但不该被拦；选了客户后问"they use what?"也没有 Stripe 词但明显在范围内。

**第二层 — LLM 兜底 + 安全网** [`app/intent.py:275`](app/intent.py#L275)：走 LLM 路径时，prompt 明确列出 out_of_scope 选项，但同时有三条硬约束抵消 LLM 的过度拒答倾向：
- 含 Stripe 信号词 → 强制改为 `general_inquiry`
- 有客户档案 → 强制改为 `general_inquiry`
- 置信度 < 0.25 → 拦截

**为什么需要安全网？** 因为 LLM 过度理解了"sales intent classifier"这个角色，把纯产品知识问题也判成 out_of_scope。真实 badcase：**"What is Stripe Terminal?" → out_of_scope**，以及 **"Can we conduct our own penetration test?" → out_of_scope**（"penetration test" 当时不在信号词里）。两个都是明显在范围内的问题。

修复是双管齐下：把 "penetration test"/"pen test" 加进信号词，同时在 LLM prompt 里加 "Questions about what a Stripe product IS should be classified by its use case, NOT out_of_scope"。

**管线短接** [`app/graph.py:272`](app/graph.py#L272)：`intent.scenario_id == "out_of_scope"` 时跳过 ReAct 和两次 SYNTH LLM 调用，直接返回固定话术，但**仍然写 session 和 metrics**——否则下一轮就看不到这次交互了。

### Q38："一个 query 包含多个意图怎么处理？"

**回答：** `IntentResult.all_matched` [`app/intent.py:64`](app/intent.py#L64) 记录所有匹配到的场景。主意图（关键词匹配数最多）选为 skill，副意图注入 THINK system prompt [`app/graph.py:159`](app/graph.py#L159)：

```
MULTI-INTENT: This query also matched these topics:
  - B2B Invoicing: You are a Stripe Invoicing specialist.
  - Security & Compliance Review: You are a Stripe security and compliance specialist.
Address ALL of these topics in your response. Use the appropriate tools for each topic.
```

每个副意图取对应 SkillConfig 的 `system_prompt` 首行（领域引导），最多注入 3 个。

**为什么不切换 skill？** 因为副意图需要的工具在主 skill 的白名单里通常已经有了（`search_product_info` 是通用的），切换 skill 只会丢失主意图的领域提示。**注入而非切换**，一次搞定。

**局限：** 只注入了首行提示，没有注入副意图的 `response_hint` 和 `escalation_triggers`。所以一个 `pricing + security` 的复合查询，只有 pricing 的升级规则会生效。当前规模下可以接受。

### Q36："SSE 流式推送怎么实现的？为什么不用 WebSocket？"

**回答：** `stream_agent()` [`app/graph.py:605`](app/graph.py#L605) 把 `_run_pipeline()` 的 `(event, payload)` 元组包成 SSE 帧。FastAPI 的 `StreamingResponse` [`app/main.py:99`](app/main.py#L99) 设 `media_type="text/event-stream"` + `Cache-Control: no-cache` + `X-Accel-Buffering: no`（防 nginx 缓冲）。

**为什么 SSE：**
- 只需要服务端→客户端单向推送，不需要双向
- HTTP 原生，无握手、无额外框架
- 穿透代理和防火墙没问题
- 断线重连浏览器原生支持

**为什么不用原生 `EventSource`：** 它只支持 GET，无法传 POST body。前端改用 Fetch API + `ReadableStream` 手动读取 chunk 并解析 SSE 格式。

**并发：** 每个请求独立创建生成器实例，无共享可变状态。会话隔离靠 `session_id`。

**当前的局限（见 Q53）：** 这是**阶段级**流式，不是 token 级。最终答案仍然要等 SYNTH 整体完成。

### Q39："多轮中的升级怎么处理？第一轮问 SOC 2，第二轮说 connect me to compliance team。"

**回答：** 三层决策。

1. **规则层** [`app/escalation.py:81`](app/escalation.py#L81)：第二轮的 query 含 "connect me to"，命中 `escalation_request` 的触发词——**但前提是这一轮被分类为 `escalation_request`**。如果被分类成 `security_compliance`（延续上一轮），Gate A 就直接拒绝了（该场景无 triggers）。

2. **上下文 LLM 层** [`app/escalation.py:166`](app/escalation.py#L166)：规则未命中 **且** 有对话历史 **且** 场景有 triggers → `escalate_with_context()` 把摘要 + 当前 query 发给 LLM。prompt 极其严格：列出四类明确不该升级的情况（账户查询、产品问题、定价咨询、任何 AI 能用工具解决的）。

3. **STAY。**

**这个例子暴露的真实问题：** 升级判断依赖意图分类的准确性。如果第二轮被继承成 `security_compliance`（该场景 triggers 为空），三层全部走不通，用户的明确转人工请求会被忽略。

**当前的缓解：** `escalation_request` 的 13 个触发短语同时也是意图分类的强信号——"connect me with" 这类短语在 KG 的 `escalation_request` 场景 question_patterns 里，会让关键词分类直接命中该场景，绕开继承逻辑。**这是靠两套关键词表的重合度兜底的，比较脆弱。**更稳的做法是在 escalation 层独立扫描一次原始 query，不依赖场景分类结果。

---

## 十二、关键技术细节速查

| 问题 | 答案 | 代码位置 |
|---|---|---|
| chunk_size / overlap | 500 / 80 | `app/milvus_loader.py:52-53` |
| embedding 模型 / 维度 | text-embedding-3-small / 1536 | `app/milvus_loader.py:51,287` |
| LLM 推理模型 | gpt-4o-mini（全部调用） | `app/graph.py:56` |
| KG 节点 / 边 | 80 / 150 | `knowledge_base/knowledge_graph.yaml` |
| KG 实体类型 | 8 种（payment_method 24、product 16、sales_scenario 13…） | `app/kg_builder.py:44` |
| KG 关系类型 | 9 种（integrates_with 33、supports_method 30…） | `app/kg_builder.py:57` |
| SkillConfig 条目 | 14（12 产品 + escalation_request + out_of_scope） | `app/skills.py:44` |
| 可分类场景 | 13（out_of_scope 是终止态） | `app/skills.py` |
| SkillConfig 字段 | 8 个 | `app/skills.py:13` |
| Tool 数量 | 6（1 RAG + 3 SQL + 1 文件读 + 1 决策） | `app/tools.py:328` |
| chunk 总数 | 278 | Milvus `stripe_sales_knowledge` |
| 相似度 / 索引 | COSINE / AUTOINDEX | `app/milvus_loader.py:222-223` |
| 最大 ReAct 迭代 | 0-3（按场景） | `app/skills.py` |
| 实测平均迭代 | 1.30 | `turn_metrics` |
| Token 预算 | 4000 total / 1500 reserved / 2500 可用 | `app/context.py:24-26` |
| 保留原始轮次 | 3 | `app/context.py:27` |
| intent 置信度阈值 | 0.6 | `app/intent.py:25` |
| out_of_scope 阈值 | 0.25 | `app/intent.py:26` |
| context boost | +0.15 | `app/intent.py:27` |
| 模糊查询判定 | ≤5 词 或含 it/that/this/they/them/those/these | `app/intent.py:42` |
| 超短跟进继承 | ≤2 词 → 直接继承上轮场景，跳过 LLM | `app/intent.py:177` |
| Stripe 信号词 | 40 个 | `app/intent.py:31-39` |
| out_of_scope 快速通道 | 0 场景 + 0 信号词 + 0 历史 + 0 客户 → 拦截（3ms） | `app/intent.py:165` |
| out_of_scope 安全网 | 有信号词 / 有客户档案 → 强制 general_inquiry | `app/intent.py:275` |
| 管线短接 | 跳过 ReAct + 两次 SYNTH，仍写 session/metrics | `app/graph.py:272` |
| 升级合格场景 | 4 / 14（marketplace, tax, pricing, escalation_request） | `app/skills.py` |
| 永不自动升级 | 9 / 13 可分类场景 | `app/skills.py` |
| 升级团队 | 7 个 | `app/escalation.py:30` |
| 升级路由表 | 40 条短语 → 团队（含当前不可达的条目） | `app/escalation.py:30` |
| 升级三层 | 规则 → 上下文 LLM（仅多轮+有 triggers）→ STAY | `app/escalation.py:81,166` |
| 交易额阈值 | >$1M → Deal Desk；>$10M → Enterprise（仅 pricing 类场景） | `app/escalation.py:114` |
| 升级确认 | `escalation_pending` → UI 确认 → `/confirm-escalation` | `app/main.py:113` |
| SQLite 并发 | WAL + busy_timeout 5000 + 单连接缓存 | `app/database.py:27` |
| 数据库表 | 7（5 原有 + session_memory + turn_metrics） | `app/database.py`, `app/metrics.py` |
| LLM 重试 | 3 次，指数退避 1.5^n，4xx 不重试 | `app/graph.py:55` |
| Tool 错误处理 | `ERROR:` 前缀 + `is_error`，连续 2 次强制合成 | `app/graph.py:395,433` |
| 工具输出格式 | 结构化 JSON，三形态：`_ok` / `_empty` / `ERROR:` | `app/tools.py:38` |
| 工具缓存 | 会话级，TTL 900s，50 条/会话，200 会话 | `app/tool_cache.py:24` |
| 缓存键 | `tool:sha256(sorted_args)[:16]`，顺序无关 | `app/tool_cache.py:65` |
| 缓存排除 | `check_escalation_tool` + 所有 `ERROR:` 输出 | `app/tool_cache.py:30,110` |
| 实测缓存命中率 | 0.424 | `turn_metrics` |
| 客户预加载 | 调真实工具注入 tool_results，走缓存 24.4ms→0.8ms | `app/graph.py:114` |
| 客户防误拦 | `has_customer_profile` → 不得判 out_of_scope | `app/intent.py:283` |
| 多意图 | `all_matched` → 副意图 system_prompt 首行注入（最多 3 个） | `app/intent.py:64`, `app/graph.py:159` |
| 占位符防止 | 客户真名注入 SYNTH + 禁止签名/占位符 | `app/graph.py:485-505` |
| 上下文分层 | 摘要 → 最近 3 轮（截断而非丢弃）→ 旧轮 200 字符 | `app/context.py:98` |
| 长轮次截断 | 二分查找 token 边界 → 退到句子边界 | `app/context.py:157` |
| 摘要触发 | 总 token > 2500 且 turns > 3 | `app/context.py:191` |
| 指标字段 | intent 路径 / 工具 / token / 分阶段延迟 / 缓存 / 错误 | `app/metrics.py:78` |
| 指标端点 | `GET /api/metrics?days=7` | `app/main.py:130` |
| 实测平均延迟 | 9865ms（20 轮） | `turn_metrics` |
| 延迟大头 | SYNTH 60-70%（两次串行 LLM，可并发化） | `turn_metrics.latency_stages` |
| intent 两条路径耗时 | keyword 0.9ms vs LLM 1674ms | `turn_metrics.latency_stages` |
| 实测每轮成本 | ≈ $0.0008（gpt-4o-mini） | 由 `tokens_in/out` 推算 |
| 单元测试 | 198 个，约 5 秒，零外部依赖 | `tests/` |
| 集成测试 | 5 个（marker 分离）+ `test_e2e.py` 12 轮 | `pytest.ini` |
| 测试分层命令 | `pytest -m "not integration"` | `pytest.ini` |
| SSE 事件类型 | 9 种：act/intent/skill/think/observe/synth/escalation/done/error | `app/graph.py` |
| 流式粒度 | **阶段级**，非 token 级（SYNTH 未开 `stream=True`） | `app/graph.py:605` |
| 前端流式读取 | Fetch + `ReadableStream`（`EventSource` 只支持 GET） | `app/static/index.html` |
| 并发瓶颈顺序 | Milvus Lite 文件锁 → SQLite 写 → 单连接 → OpenAI 限流 | — |
