# Research Investigation Skill — AI 帮你做 Idea 尽调

[English](README.en.md) | 中文

## 这是什么

你有一个 idea——比如「做一个 AI 语音记账 App，老年人对着说话就能自动记账」——但心里没底：

- 这东西是不是早就有人做过了？
- 核心的技术假设靠不靠谱？
- 真正的创新点（如果有的话）在哪？
- 到底值不值得投入去做？

这个 Skill 就是用 AI 帮你回答这些问题的调研工具。它不是「搜一下、贴一堆链接」的资料汇总，而是像做尽职调查一样工作：把你的 idea 拆成一条条可验证的主张（Claim），逐条去论文库、GitHub、互联网和已有产品里找证据，最后输出一份**每条结论都有出处**的调研报告，并给出明确建议：

| 建议 | 含义 |
|---|---|
| `DO` | 证据支持，值得做 |
| `MODIFY` | 方向对，但需要调整（会指出改哪里） |
| `PIVOT` | 原方向不成立，但发现了相邻的可做机会 |
| `DON'T_DO` | 已有几乎相同的工作，或核心假设被证据推翻 |
| `INSUFFICIENT_EVIDENCE` | 查完预算仍无法裁决，不强行下结论 |

报告里每条结论都带着证据编号，可以一路回溯到原始论文、代码仓库或网页——AI 说的每句话都有出处，你不用「信不信由你」。

## 功能描述

- **Idea 拆解**：把一段自然语言描述拆成 5 条以上原子 Claim，按技术 / 产品 / 市场 / 用户问题等分类，标出哪些是必须验证的关键假设。
- **四通道取证**：学术论文（OpenAlex / Crossref / arXiv）+ 开源代码（GitHub）+ 通用网页 + 已有产品，避免只看单一来源就下结论。
- **逐条裁决**：每条 Claim 得出五态结论（支持 / 部分支持 / 被反驳 / 未知 / 证据不足），附置信度和理由；**没查到证据会被如实标注为「证据不足」，而不是当作「没人做过」**。
- **Prior Art 分析**：把已有工作与你的 idea 按「问题 / 方法 / 系统 / 评估」四个维度比对，给出从「完全相同」到「不相关」的五档相似度和具体差异说明。
- **Novelty 评级**：从 none 到 breakthrough 五档，必须给出依据，不允许「感觉挺新的」这种判断。
- **可行性分析**：技术瓶颈分为工程问题（堆人能解决）/ 研究问题（方法还没人验证）/ 根本性问题（受能力边界限制）三类，帮你判断难度性质。
- **成熟度甄别**：区分「有论文」「有代码」「有产品」「验证过市场」——论文存在 ≠ 技术成熟，不会把一个 demo 说成是成熟方案。
- **预算与自动收口**：每个检索通道有查询上限，证据饱和自动停止；预算耗尽时强制收口出报告，不会无限搜索也不会硬凑结论。
- **14 节调研报告**：从执行摘要、主张清单、已有工作综述，到瓶颈分析、风险声明和建议的下一步，结构完整可直接用于汇报。

## 使用场景

**适合用：**

- 动手做 side project / 毕业设计选题 / 创业方向之前，想先确认这个方向有没有人做过、还有没有差异化空间。
- 写论文或申请项目前，需要一份 novelty 论证材料。
- 手里只有一个模糊方向，想快速摸清学术界和工业界的现状。
- 需要一份「每个结论都能查到出处」的调研报告（给导师、老板或合作方看）。

**直接用自然语言发起即可**，例如：

> 帮我调研一下这个 idea 靠不靠谱：做一个 AI 语音记账 App，老年人对着说话就能自动记下花销……
>
> 这个方向有人做过吗？值不值得做？
>
> 我想做基于 LLM 的代码评审工具，先帮我做个 novelty 分析。

**不适合用：**

- 只想要某个主题的资料汇总 / 文献综述 → 用普通搜索或 `web-research-summarizer`。
- 只想读某个具体网页 → 直接给链接。
- 已经决定要做，只想要实现方案 → 直接问实现，不需要调研。

## 快速开始

### 1. 前置要求

- 任一支持 Agent Skills 规范的 agent：Claude Code、Cursor、Trae、WorkBuddy 等；宿主需具备内置 WebSearch / WebFetch 能力（网页与产品通道依赖它）。
- Python 3.8+：检索脚本使用，纯标准库，无需 `pip install`。

### 2. 安装到你的 Agent

Skill 以 `SKILL.md` 为入口，两种安装方式任选其一：

**方式一：GUI 手动导入（无需命令行）**：WorkBuddy / Trae 等 GUI Agent 可直接下载本项目的 zip 包，在 Agent 的 skill 管理界面中手动导入。

**方式二：放入 skills 目录**：把整个仓库放入（或软链到）目标 agent 的 skills 目录，**目录名保持 `research-investigation`**：

| Agent | 用户级（全局生效） | 项目级（仅当前项目） |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Cursor | `~/.cursor/skills/` 或 `~/.agents/skills/` | `.cursor/skills/` 或 `.agents/skills/` |
| Trae | `~/.trae/skills/` | `.trae/skills/` 或 `.agents/skills/` |
| WorkBuddy | `~/.workbuddy/skills/` | — |

> Windows 下 `~` 对应 `%USERPROFILE%`。

macOS / Linux，推荐软链（仓库更新后即时生效）：

```bash
cd /path/to/Research-Investigation-Skill
ln -s "$(pwd)" ~/.claude/skills/research-investigation   # Claude Code
ln -s "$(pwd)" ~/.cursor/skills/research-investigation   # Cursor
ln -s "$(pwd)" ~/.trae/skills/research-investigation     # Trae
```

Windows PowerShell（需管理员权限）：

```powershell
New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\research-investigation" -Target "C:\path\to\Research-Investigation-Skill"
```

不用软链直接复制也可以（`cp -r` 到目标目录），缺点是仓库更新后需重新复制。

安装后**重启 agent 会话**（或新开一个会话），skill 才会被发现和加载。

### 3. 配置环境变量（可选，但建议）

```bash
export RESEARCH_MAILTO="you@example.com"   # 学术检索源 OpenAlex 必填，不带会被限流
export GITHUB_TOKEN="ghp_xxx"              # 可选，配上后 GitHub 检索额度 6 → 20
```

### 4. 验证安装（可选）

```bash
python3 tests/test_validate_state.py   # 28 项：schema / 预算 / 饱和 / 写回 / 收口
python3 tests/test_pipeline.py         # 5 项：全链路离线回归
```

更直接的方式：新会话里发起一次小调研（见下一步），看它是否按「拆解 → 取证 → 报告」流程工作。

### 5. 发起调研

在 agent 对话中直接描述你的 idea 并表达调研意图，例如：

```
帮我调研一下这个 idea：做一个 AI 语音记账 App，
老年人对着说话就能自动记下花销并生成月度报表。
```

**触发机制**：skill 主要由 agent **自动加载**——安装重启后，agent 会读取 SKILL.md 的 description；当你的请求匹配调研意图（如「这个 idea 值得做吗」「有没有人做过」）时自动接管。如果说了半天没触发，也可以手动输入 `/research-investigation` 强制调用。

Skill 会自动接管整个流程：拆解 Claim → 规划检索 → 多通道取证 → 逐条验证 → Prior Art / 可行性分析 → 生成报告。过程中所有状态落盘，中断后可续跑。

### 6. 查看结果

产出在当前项目目录的 `research/<idea-slug>/` 下：

```text
research/<idea-slug>/
├── research-state.json   # 全量状态：claims、裁决、prior art、预算使用
├── evidence.jsonl        # 证据库，一行一条，append-only
└── report.md             # 14 节调研报告 ← 主要看这个
```

## 工作原理速览

```text
Idea → Claims → 多通道搜索 → Evidence → 逐条裁决
     → Prior Art → Novelty / 可行性 → 建议 + 报告
```

六个阶段（每阶段出口有自动校验，不通过不进入下一阶段）：

| Stage | 做什么 |
|---|---|
| 0–1 | 初始化 state，把 Idea 拆成原子 Claim（≥5 条、≥3 种类型） |
| 2 | 为每条关键 Claim 规划跨通道检索 query（≥3 条） |
| 3 | 执行检索，归一化为 Evidence（去重、标强度、标成熟度） |
| 4 | 证据 → 裁决；证据不足的如实标注 `insufficient_evidence` |
| 5 | Prior Art 比对 + 瓶颈分类 + Novelty 评级 |
| 6 | 仅基于落盘状态生成报告，不掺入过程性记忆 |

## TODO

- [ ] 增加 quick / standard / deep profiles。
- [ ] 增加时间、上下文和 Fetch 限制。
- [ ] 实现 query 状态、去重和统一记账。
- [ ] 实现自动 saturation 和 Evidence top-k 裁剪。
- [ ] 优化网络重试、缓存并补充回归测试。
