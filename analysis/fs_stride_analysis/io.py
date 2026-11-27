"""Strict CSV and JSON metadata loaders for fs-stride."""

from __future__ import annotations

import csv
import json
from pathlib import Path

RAW_COLS = (
    "run_id",
    "host",
    "mode",
    "stride",
    "threads",
    "placement",
    "block",
    "order",
    "role",
    "total_ops",
    "elapsed_s",
    "ns_per_op",
    "cpus",
    "loadavg1",
)
VALID_ROLES = {"ref", "test", "sentinel"}


def load_raw(path: Path) -> list[dict]:
    """Load raw.csv, validate all 14 columns, and drop block 0 warm-up."""
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run fs_stride first")
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        cols = reader.fieldnames or []
        for col in RAW_COLS:
            if col not in cols:
                raise ValueError(f"missing column: {col}")
        extra = [c for c in cols if c not in RAW_COLS]
        if extra:
            raise ValueError(f"unexpected column: {extra[0]}")
        rows: list[dict] = []
        for row in reader:
            role = row["role"]
            if role not in VALID_ROLES:
                raise ValueError(f"invalid role: {role}")
            if not row["cpus"].strip():
                raise ValueError("empty cpus affinity field")
            blk = int(row["block"])
            if blk == 0:
                continue
            rows.append(
                {
                    "run_id": row["run_id"],
                    "host": row["host"],
                    "mode": row["mode"],
                    "stride": int(row["stride"]),
                    "threads": int(row["threads"]),
                    "placement": row["placement"],
                    "block": blk,
                    "order": int(row["order"]),
                    "role": role,
                    "total_ops": int(row["total_ops"]),
                    "elapsed_s": float(row["elapsed_s"]),
                    "ns_per_op": float(row["ns_per_op"]),
                    "cpus": row["cpus"],
                    "loadavg1": float(row["loadavg1"]),
                }
            )
    return rows


def load_meta(path: Path, schema_path: Path | None = None) -> dict:
    """Load meta.json and validate against schemas/meta.schema.json."""
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing; run fs_stride first")
    meta = json.loads(path.read_text(encoding="utf-8"))
    if meta.get("schema_version") != "2.0":
        raise ValueError("meta.json schema_version must be 2.0")
    if schema_path is None:
        cand = Path(__file__).resolve().parents[2] / "schemas" / "meta.schema.json"
        if cand.is_file():
            schema_path = cand
    if schema_path and schema_path.is_file():
        import jsonschema  # optional only when validating standalone

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(meta, schema)
    return meta
