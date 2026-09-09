# Research Investigation Skill — AI-Powered Due Diligence for Your Ideas

English | [中文](README.md)

## What Is This

You have an idea — say, "an AI voice-bookkeeping app where elderly people just talk and their expenses get recorded automatically" — but you're not sure:

- Has someone already built this?
- Are the core technical assumptions actually sound?
- Where's the real novelty, if any?
- Is it worth your time at all?

This Skill uses AI to answer those questions. It is not a "search and paste a pile of links" summarizer — it works like a due-diligence investigation: your idea is decomposed into verifiable Claims, each claim is checked against academic papers, GitHub repositories, the web at large, and existing products, and you get a fully **source-traceable** research report with an explicit verdict:

| Verdict | Meaning |
|---|---|
| `DO` | Evidence supports it — worth doing |
| `MODIFY` | Direction is right but needs adjustment (the report says what to change) |
| `PIVOT` | Original goal doesn't hold, but an adjacent opportunity exists |
| `DON'T_DO` | Nearly identical work already exists, or core assumptions are contradicted |
| `INSUFFICIENT_EVIDENCE` | Cannot be decided within the search budget — no forced conclusion |

Every conclusion in the report carries evidence IDs, so you can trace each one back to the original paper, repository, or web page. You never have to take the AI's word for it.

## Features

- **Idea decomposition** — Turns a free-text description into 5+ atomic Claims, categorized (technical / product / market / user problem, etc.), with the critical assumptions flagged.
- **Four-channel evidence gathering** — Academic papers (OpenAlex / Crossref / arXiv) + open-source code (GitHub) + the general web + existing products, so conclusions never rest on a single source type.
- **Per-claim adjudication** — Every Claim gets a five-state verdict (supported / partially supported / contradicted / unknown / insufficient evidence) with confidence and rationale. **"No evidence found" is honestly reported as `insufficient_evidence`, never as "nobody has done this."**
- **Prior Art analysis** — Compares existing work against your idea across four dimensions (problem / method / system / evaluation), assigning a five-level similarity rating with concrete difference notes.
- **Novelty rating** — Five levels from `none` to `breakthrough`, always with a justification that cites evidence — no "feels pretty novel" judgments.
- **Feasibility analysis** — Technical bottlenecks are classified as engineering (solvable with effort) / research (method unproven, needs experiments) / fundamental (bounded by existing theory or capabilities), so you know what kind of difficulty you're facing.
- **Maturity discrimination** — Distinguishes "there's a paper" from "there's code" from "there's a product" from "the market validated it." A paper existing ≠ the technology is mature; a demo never gets described as a production-ready solution.
- **Budget control & forced closure** — Every search channel has a query cap, and evidence saturation stops a line of investigation automatically. When the budget runs out, the report is still produced — with undecidable claims honestly marked, never force-fitted.
- **14-section research report** — From executive summary, claim list, and existing-work review to bottleneck analysis, risk disclosure, and recommended next steps — ready to present as-is.

## Use Cases

**Good fits:**

- Before committing to a side project, thesis topic, or startup direction — check whether it's been done and whether differentiation room exists.
- Novelty justification before writing a paper or applying for a project.
- You have only a vague direction and want to quickly map the academic and industry landscape.
- You need a research report where every conclusion has a citable source (for an advisor, manager, or partner).

**Just describe your idea in natural language:**

> Look into this idea for me: an AI voice-bookkeeping app where elderly people just talk and their expenses get recorded automatically…
>
> Has anyone built something like this before? Is it worth doing?
>
> I want to build an LLM-based code review tool — start with a novelty analysis.

**Not a fit:**

- You just want a topic summary / literature digest → use a regular search or `web-research-summarizer`.
- You want to read one specific page → just open the link.
- You've already decided to build it and only want an implementation plan → ask for the plan directly.

## Quick Start

### 1. Prerequisites

- Any agent that supports the Agent Skills convention: Claude Code, Cursor, Trae, WorkBuddy, etc. The host must provide built-in WebSearch / WebFetch (the web and product channels depend on it).
- Python 3.8+ for the search scripts — stdlib only, no `pip install` needed.

### 2. Install into your agent

The skill's entry point is `SKILL.md` — pick either installation method:

**Option 1: GUI manual import (no command line)**: GUI agents such as WorkBuddy / Trae can simply download this project's zip package and import it manually through the agent's skill management UI.

**Option 2: Drop into the skills directory**: Place (or symlink) the whole repository into your agent's skills directory, **keeping the directory name `research-investigation`**:

| Agent | User-level (available everywhere) | Project-level (current project only) |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Cursor | `~/.cursor/skills/` or `~/.agents/skills/` | `.cursor/skills/` or `.agents/skills/` |
| Trae | `~/.trae/skills/` | `.trae/skills/` or `.agents/skills/` |
| WorkBuddy | `~/.workbuddy/skills/` | — |

> On Windows, `~` corresponds to `%USERPROFILE%`.

macOS / Linux — symlink recommended (updates to the repo take effect immediately):

```bash
cd /path/to/Research-Investigation-Skill
ln -s "$(pwd)" ~/.claude/skills/research-investigation   # Claude Code
ln -s "$(pwd)" ~/.cursor/skills/research-investigation   # Cursor
ln -s "$(pwd)" ~/.trae/skills/research-investigation     # Trae
```

Windows PowerShell (run as administrator):

```powershell
New-Item -ItemType SymbolicLink -Path "$HOME\.claude\skills\research-investigation" -Target "C:\path\to\Research-Investigation-Skill"
```

A plain copy (`cp -r`) into the target directory works too — the drawback is you must re-copy after every repo update.

After installing, **restart your agent session** (or open a new one) so the skill gets discovered and loaded.

### 3. Set environment variables (optional, recommended)

```bash
export RESEARCH_MAILTO="you@example.com"   # Required by OpenAlex; without it you get rate-limited
export GITHUB_TOKEN="ghp_xxx"              # Optional; raises the GitHub query budget from 6 to 20
```

### 4. Verify the installation (optional)

```bash
python3 tests/test_validate_state.py   # 28 checks: schema / budget / saturation / merge / finalize
python3 tests/test_pipeline.py         # 5 checks: full offline pipeline regression
```

Or more directly: start a small investigation in a fresh session (next step) and see whether it follows the decompose → gather → report flow.

### 5. Start an investigation

Describe your idea and your intent in the agent conversation:

```
Investigate this idea: an AI voice-bookkeeping app where elderly
people speak naturally and their expenses are recorded with monthly reports.
```

**Triggering**: The skill is **auto-loaded by the agent** — after installation and a session restart, the agent reads the description in `SKILL.md`; when your request matches an investigation intent (e.g., "is this idea worth doing?", "has anyone done this before?"), it takes over automatically. If it doesn't trigger after a few tries, you can force it by typing `/research-investigation` manually.

The Skill takes over the whole pipeline: decompose claims → plan searches → gather evidence across channels → verify each claim → prior art / feasibility analysis → generate the report. All state is written to disk, so an interrupted run can be resumed.

### 6. Read the results

Output lands under `research/<idea-slug>/` in the current project:

```text
research/<idea-slug>/
├── research-state.json   # Full state: claims, judgments, prior art, budget usage
├── evidence.jsonl        # Evidence store, one entry per line, append-only
└── report.md             # 14-section research report ← start here
```

## How It Works

```text
Idea → Claims → multi-channel search → Evidence → claim verification
     → Prior Art → novelty / feasibility → recommendation + report
```

Six stages (each stage exit is gated by automatic validation — failure blocks progression):

| Stage | What happens |
|---|---|
| 0–1 | Initialize state; decompose the idea into atomic Claims (≥5 claims, ≥3 types) |
| 2 | Plan cross-channel queries for each critical Claim (≥3 each) |
| 3 | Run searches; normalize results into Evidence (dedupe, strength, maturity) |
| 4 | Evidence → judgment; claims without evidence are honestly marked `insufficient_evidence` |
| 5 | Prior Art comparison + bottleneck classification + novelty rating |
| 6 | Report generated from on-disk state only — no transient context leaks in |
