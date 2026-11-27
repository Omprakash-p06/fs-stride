# Authorship & Experimental Verification Disclosure (`NFR-10`)

This file records which components of `fs-stride` were AI-assisted and which experiments, measurements, and statistical checks were personally executed and verified by the human author.

## Human-Verified Experiments & Pilot Runs

- *Pending Block 1–3 implementation:* Pilot run (`make all` / `make sweep`), hardware topology verification (`sched_getcpu()`), and bare-metal ablation runs will be recorded here with machine model, date, kernel version, and run ID.

## AI-Assisted Components

- Planning, Goldfish design review, and contract scaffolding (`docs/decisions.md`, `src/fs_stride.h`, `schemas/*.schema.json`, `data/folklore.toml`, documentation edits): AI-assisted; reviewed and approved by the human author.
- Commits containing AI-assisted code carry an `Assisted-by:` trailer alongside `Signed-off-by:` per `AGENTS.md` §3.4.
