# 检索通道配置

四个抽象能力名（`academic_search` / `github_search` / `web_search` / `product_search`）与具体端点的对应。
SKILL.md 只暴露能力名，替换数据源时改这里，不动提示词。

## 网络层

`scripts/_common.py` 的 `http_get` 统一处理出网，回退链固定为：

```text
env 代理（端口每次会话都变，只能从 HTTPS_PROXY 读）
  → 127.0.0.1:7897（本机 Clash 混合端口）
  → 返回 err，由调用方判定通道不可用
```

- 4xx（除 429）不重试，直接失败——请求本身有问题，换代理没用。
- 429 / 503 退避重试 2 次（3s、6s）。
- 沙箱代理是**域名白名单**，端口每次会话变化（实测 49964 / 54811），禁止硬编码。

## 通道

| 能力名 | 实现 | 端点 | 鉴权 | 限额 | 网络路径 | 状态 |
|---|---|---|---|---|---|---|
| `academic_search` | OpenAlex | `api.openalex.org/works` | 无，但**必须带 `mailto`** | 10 req/s | env 代理（白名单内） | ✅ 主通道（⚠️ 间歇 503，见下） |
| `academic_search` | Crossref | `api.crossref.org/works` | 无，`mailto` 走 polite pool | 较宽松 | env 代理（白名单内） | ✅ 副通道（DOI 校验）＋ **OpenAlex 503 时的替代主通道** |
| `academic_search` | arXiv | `export.arxiv.org/api/query` | 无 | 官方建议 3s/req | 7897 / WebFetch | ⚠️ 见下 |
| `github_search` | GitHub Search API | `api.github.com/search/repositories` | `GITHUB_TOKEN` 可选 | 匿名 **10 req/min**、core 60/hr | env 代理（白名单内） | ✅ |
| `web_search` | 内置 WebSearch + WebFetch | — | — | — | 内置工具，不经沙箱 | ✅（Agent 侧，非脚本） |
| `product_search` | WebSearch（Product-Lite）+ agent-browser | — | — | — | 内置工具 | ✅（Agent 侧） |

额度不写死在脚本里，存在 `state.search_budget.by_channel` 的 `max_queries` / `max_results`。

## 各源要点

### OpenAlex

- **不带 `mailto` 稳定返回 429**；带任意邮箱即可进 polite pool。用环境变量 `RESEARCH_MAILTO` 设置。
- 用 `filter=title_and_abstract.search:{q}`，**不要用 `search={q}`**：后者是全文本匹配，
  会混入只在参考文献里提过一次关键词的论文（实测混入过无关医学论文）。
- `abstract_inverted_index` 是 `{词: [位置]}`，需还原语序（脚本已处理）。
- 已收录 arXiv 预印本（实测 25 条结果中 3 条来自 arXiv），因此 arXiv 不可用时仍有覆盖。
- ⚠️ **OpenAlex 会间歇性整段返回 HTTP 503（实测 2026-09-10 一轮：13 次调用中 5 次 503，
  且退避重试 3s/6s 无效），不是瞬时抖动，而是持续数十秒的不可用窗口。**
  `search_academic.py` 因此会反复向 `unavailable_channels` 追加同名记录——**这是通道抖动，
  不等于通道失效**，不要据此停止整个 academic 通道。处置方式：
  1. 立即用 `--source crossref` 重跑同一条 query（Crossref 在本机从未出现该问题）；
  2. **规划额度时必须给 academic 留 2–3 条冗余 query**，因为失败重跑会占用 `max_queries` 名额
     （注意：脚本只在**成功**时记账，`queries=len(sources)-len(failures)`，失败不扣额度，
     但跨通道重跑会扣对应通道的额度）。
  3. 常见的连带损失是 **Crossref 缺 `abstract`**，导致该条 Evidence 拿不到 `evidence` 摘录、
     `relevance` 只能给到 0.5 以下而进不了报告。遇到这种条目要单独在报告 §11 声明，
     不能当成「已覆盖」。

### Crossref

- `abstract` 字段常缺失，且带 JATS 标签与 HTML 实体（脚本已 `unescape` + 去标签）。
- 期刊质量参差，需靠归一化阶段的 `relevance` 过滤。

### arXiv

- 直连 API 在本机共享出口 IP 上稳定返回 `429 Rate exceeded.`，退避重试无效——
  这是 IP 级限流，不是瞬时抖动。
- 处理方式：脚本失败会写入 `unavailable_channels`；改用两条替代路径
  1. `--source openalex`（已含 arXiv 预印本）
  2. Agent 用内置 WebFetch 查 `arxiv.org`（不经沙箱，不受白名单与出口 IP 影响）
- **通道不可用 ≠ 没有 prior work**。必须写进 `unavailable_channels` 并在报告 §11 声明覆盖缺口。

### GitHub

- 匿名 10 req/min。脚本检测到 `GITHUB_TOKEN` 时会自动把 state 里 github 通道的 `max_queries` 提到 20。
- 403 / 429（rate limit）→ 写入 `unavailable_channels` 并退出 1，不静默失败。
- 仓库只能证明「有代码」：`implementation_level` 一律写 `code`。升级到
  `prototype` / `production` / `commercial_product` 需要额外证据，由归一化阶段判定。

## 字段映射默认值

| 源 | `source_type` | `implementation_level` | `strength` 启发式 |
|---|---|---|---|
| OpenAlex | `academic` | `paper` | 被引 ≥20 → high，否则 medium |
| Crossref | `academic` | `paper` | medium |
| arXiv | `academic` | `paper` | medium |
| GitHub | `github` | `code` | stars ≥500 → high，否则 medium |

`relevance` 一律先填 `0.5`，由 Stage 3 的归一化阶段校准——脚本不做语义判断。
报告阶段只载入 `relevance >= 0.6` 的条目，因此**归一化是必经步骤，不是可选项**。

## 失败约定

脚本级通道失败 → `mark_unavailable` 写入 `unavailable_channels[]`（含原因与时间）。
任何情况下都不得把它推导为「没有相关工作」。
