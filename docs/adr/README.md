# Architecture Decision Records (`docs/adr/`)

This directory contains the Architecture Decision Records (ADRs) for `fs-stride`. Together with [decisions.md](../decisions.md), [RESEARCH_PLAN.md](../RESEARCH_PLAN.md), and [fs-stride Complete Project Specification v2.0.md](../fs-stride%20Complete%20Project%20Specification%20v2.0.md), the files under `docs/` form the **final source of truth** for:

1. **One-shot implementation** (`src/`, `analysis/`, `scripts/`, `tests/`, `schemas/`, `data/`).
2. **GSD planning and execution** (`.planning/PROJECT.md`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`, phase plans, and verification artifacts).
3. **Graphicle knowledge graph and queries** (`graphicle sync`, `recall_project`, `query_graph`, `get_node`, `get_neighbors`).

> **Global Process Standard:** [AGENTS.md](../../AGENTS.md) is the global process standard enforced across Claude Code (`CLAUDE.md`), OpenCode (`OPENCODE.md`), Codex (`CODEX.md`), Antigravity (`ANTIGRAVITY.md`, `GEMINI.md`), GitHub Copilot (`.github/copilot-instructions.md`), and T3 Code (`T3CODE.md`). While `AGENTS.md` governs *how* agents work (Consequence Briefs, frozen invariants, branching, PRs, testing gates), `docs/` governs *what* is built and *why*.

---

## Source-of-Truth Hierarchy

| Concern | Precedence (Highest to Lowest) |
| :--- | :--- |
| **Process & Governance** | `AGENTS.md` (enforced via `CLAUDE.md`, `OPENCODE.md`, `CODEX.md`, `ANTIGRAVITY.md`, `GEMINI.md`, `T3CODE.md`, `.github/copilot-instructions.md`) |
| **Design Decisions & Trade-offs** | `docs/adr/` + `docs/decisions.md` > `docs/RESEARCH_PLAN.md` > `docs/fs-stride Complete Project Specification v2.0.md` > `README.md` |
| **Interface Contracts (FRs, NFRs, Test IDs, Schemas, CLI)** | `docs/fs-stride Complete Project Specification v2.0.md` + (`src/fs_stride.h`, `schemas/*.schema.json`, `data/folklore.toml`) > `docs/adr/` + `docs/decisions.md` > `docs/RESEARCH_PLAN.md` > `README.md` |

---

## How Decisions Must Be Made (GSD, Graphicle, and Agents)

Every technical, architectural, statistical, or schema decision must follow these five rules:

1. **Read All Authoritative `docs/` Before Acting:**
   - Check [decisions.md](../decisions.md) and `docs/adr/*.md` first for resolved choices.
   - Check [RESEARCH_PLAN.md](../RESEARCH_PLAN.md) for microarchitectural, runtime, and statistical proof (`Defects 1–4`, `Flaws 1–4`, `Calculations 1–6`).
   - Check [fs-stride Complete Project Specification v2.0.md](../fs-stride%20Complete%20Project%20Specification%20v2.0.md) for `FR-*`, `NFR-*`, `UT-*`, `IT-*`, `NT-*`, `ST-*`, and backlog IDs (`T00–T20`).
   - Check [related-work.md](../related-work.md) and [AUTHORSHIP.md](../AUTHORSHIP.md) for citation boundaries and provenance.

2. **No Contradictions in GSD (`.planning/`):**
   - GSD roadmaps, phase specs, and `PLAN.md` tasks under `.planning/` are derived from `docs/`, never the reverse.
   - If a GSD plan discovers a gap or proposes altering a requirement, threshold, schema, or algorithm, **do not silently patch `.planning/` or code**—record an ADR here first.

3. **Graphicle Scope Alignment:**
   - `.graphicleignore` excludes large narrative/archival prose (`docs/RESEARCH_PLAN.md`, `docs/fs-stride Complete Project Specification v2.0.md`, `docs/related-work.md`, `docs/AUTHORSHIP.md`, `paper/`, `results/`, `data/*/`, `tests/fixtures/`) and AI harness files so Graphicle stays small and focused on code (`src/`, `analysis/`, `scripts/`, `tests/`), contracts (`schemas/`, `data/folklore.toml`), [decisions.md](../decisions.md), and `docs/adr/`.
   - Keep `docs/decisions.md` and `docs/adr/*.md` concise and declarative so Graphicle `recall_project` and `query_graph` resolve design intent cleanly alongside symbol connections.

4. **Check Frozen Invariants (`AGENTS.md` §0.3–0.4):**
   - Decisions touching frozen symbols (`run_cell`, `make_schedule`, `alloc_counters`, `topo_pick`, `paired_t`, `holm`, `mde90`, `knee`, `classify_config`, `simulate_sweep`, `load_raw`, `run_all.sh`, `data/folklore.toml`, `paper/main.tex`) require a Consequence Brief (`AGENTS.md` §0.1), `make test-sim` evidence (once implemented), two reviewers, and explicit human sign-off.

5. **Record Every New Decision Atomically:**
   - Create `docs/adr/000N-<short-slug>.md` with sections: **Status**, **Context**, **Options Considered**, **Decision**, **Consequences & Blast Radius**, and **Source References** (citing exact `docs/` sections).
   - Update [decisions.md](../decisions.md), [fs-stride Complete Project Specification v2.0.md](../fs-stride%20Complete%20Project%20Specification%20v2.0.md), and [AGENTS.md](../../AGENTS.md) (if process or frozen invariants change) in the same commit/PR.

---

## ADR Index

| ADR | Title | Status | Scope |
| :--- | :--- | :--- | :--- |
| [0001](0001-canonical-truth-gsd-and-graphicle.md) | Canonical `docs/` Source of Truth, GSD/Graphicle Boundaries, and Phasing | Accepted | Governance, GSD, Graphicle, MVP vs Phase 2 |
| [0002](0002-kernel-modes-allocator-and-pinning.md) | 5-File C Architecture, Modes, Placements, `posix_memalign`, and `K=65,536` Loop | Accepted | `src/`, `raw.csv`, `UT-01`–`UT-06`, `UT-14` |
| [0003](0003-paired-log-ratio-holm-and-mde90.md) | Paired Log-Ratio Holm (`m=5`), 1% Floor, `MDE90` Gate, and `s >= s*` Knee Rule | Accepted | `analysis/`, `schemas/`, `ST-01`–`ST-03` |
