# ADR 0001: Canonical `docs/` Source of Truth, GSD/Graphicle Boundaries, and Phasing

- **Status:** Accepted
- **Date:** 2026-11-27
- **Decides:** Governance hierarchy, GSD `.planning/` authority, Graphicle indexing scope, Phase 1 MVP vs Phase 2 split (`docs/decisions.md` #13, #14).

## Context

`fs-stride` is a measurement paper where small changes to C kernels, thread pinning, timing loops, or Python statistics invalidate empirical claims. Prior to resolution, `docs/RESEARCH_PLAN.md` and `docs/fs-stride Complete Project Specification v2.0.md` contained conflicting interface details, while multiple AI coding harnesses (Claude Code, OpenCode, Codex, Antigravity, GitHub Copilot, T3 Code) and tooling layers (GSD `.planning/`, Graphicle MCP) needed a unified process and source-of-truth contract.

## Options Considered

1. **Maintain separate per-harness rules and allow GSD `.planning/` files to evolve independently of `docs/`:** Rejected; causes split-brain drift between harnesses and specifications.
2. **Index all prose documents, audit tables, and paper drafts in Graphicle:** Rejected; large narrative Markdown files (`docs/RESEARCH_PLAN.md` alone is >300 lines of prose and calculations) bloat the graph and obscure symbol-level code connections.
3. **Establish `AGENTS.md` as global process standard + `docs/` as final truth + `.graphicleignore` for non-code prose:** Chosen.

## Decision

1. **`AGENTS.md` is the global process standard:** Root entry points (`CLAUDE.md`, `OPENCODE.md`, `CODEX.md`, `ANTIGRAVITY.md`, `GEMINI.md`, `T3CODE.md`, `FREEBUFF.md`, `.github/copilot-instructions.md`) delegate exclusively to `AGENTS.md` and `docs/`. All AI harness files, `.planning/`, MCP configs, and `.graphicle*` artifacts are `.gitignore`d.
2. **`docs/` is the final source of truth for one-shot implementation and GSD:** Every GSD roadmap, phase plan, and implementation task must derive from [decisions.md](../decisions.md), `docs/adr/`, [RESEARCH_PLAN.md](../RESEARCH_PLAN.md), and [fs-stride Complete Project Specification v2.0.md](../fs-stride%20Complete%20Project%20Specification%20v2.0.md).
3. **Graphicle indexes code, contracts, and concise ADRs only:** `.graphicleignore` excludes narrative/archival docs (`RESEARCH_PLAN.md`, `Spec v2.0.md`, `related-work.md`, `AUTHORSHIP.md`, `README.md`, `paper/`, `results/`, `data/*/`, `tests/fixtures/`) so Graphicle focuses on `src/`, `analysis/`, `scripts/`, `tests/`, `schemas/`, `data/folklore.toml`, `docs/decisions.md`, and `docs/adr/`.
4. **Two-phase execution:** Phase 1 MVP delivers `T00–T13` (`make smoke`, `make test-sim`, local pilot, `ci.yml` with hard `cloc <= 400 C / <= 600 Python` gate, weekly `measure.yml`). Phase 2 (after Gate G1) adds `T14–T20` (`c2c_check.sh`, `msr_ablate.sh`, `release.yml`, `validate-data.yml`, `resolve_pins.sh`, `license_check.sh`, `atlas.md` + `knee_by_machine.png`, Compile Farm runs, `paper/main.tex`).

## Consequences & Blast Radius

- All harnesses follow identical Consequence Brief, frozen-invariant, and verification rules.
- Graphicle graphs stay small, fast, and focused on source-file and function dependencies while preserving architectural decisions via `docs/decisions.md` and `docs/adr/`.
- Changing MVP vs Phase 2 scope requires a new ADR updating `Spec v2.0.md` §14/§16 and `AGENTS.md` §13.1.
