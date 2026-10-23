#!/usr/bin/env python3
"""Offline parser for the versioned PPI_DIAG firmware trace.

This is a provenance parser, not a beat or HRV classifier.  It retains every
matched line in arrival order and deliberately makes no continuity claim.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

U32_MAX = 2**32 - 1
INT_RE = re.compile(r"^-?[0-9]+$")
MARKER_RE = re.compile(r"(?:^|\s)PPI_DIAG(?:\s|$)")

SCHEMA: dict[str, set[str]] = {
    "result": {"v", "stage", "rid", "frame", "count", "confidence", "wear", "ticks"},
    "interval": {"v", "stage", "rid", "frame", "index", "ppi", "quality", "ticks", "accepted", "skip"},
    "manager": {"v", "stage", "rid", "frame", "index", "ppi", "quality", "ticks", "accepted", "skip"},
    "app": {"v", "stage", "rid", "frame", "index", "ppi", "quality", "ticks", "accepted", "skip"},
}
REQUIRED = {
    "result": {"v", "stage", "rid", "frame", "count", "confidence", "wear", "ticks"},
    "interval": {"v", "stage", "rid", "index", "ppi", "quality", "ticks", "accepted", "skip"},
    "manager": {"v", "stage", "rid", "index", "ppi", "quality", "ticks", "accepted", "skip"},
    "app": {"v", "stage", "rid", "index", "ppi", "quality", "ticks", "accepted", "skip"},
}

RANGES = {
    "rid": (0, U32_MAX), "frame": (0, U32_MAX),
    "ticks": (0, U32_MAX), "count": (-(2**31), 2**31 - 1),
    "confidence": (-(2**31), 2**31 - 1), "wear": (0, 1),
    "index": (0, 3), "ppi": (-(2**31), 2**31 - 1), "quality": (0, 255),
    "accepted": (0, 1), "skip": (0, 4),
}


def _int(value: str, field: str) -> int:
    if not INT_RE.fullmatch(value):
        raise ValueError(f"{field} must be a decimal integer")
    number = int(value)
    low, high = RANGES[field]
    if number < low or number > high:
        raise ValueError(f"{field} out of range")
    return number


def _parse_line(line: str, line_no: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    marker = re.search(r"(?<![A-Za-z0-9_])PPI_DIAG(?=\s|$)", line)
    if not marker:
        return None, None
    payload = line[marker.start():].strip().split()[1:]
    fields: dict[str, str] = {}
    errors: list[str] = []
    for token in payload:
        if "=" not in token:
            errors.append(f"token_without_equals:{token}")
            continue
        key, value = token.split("=", 1)
        if not key or not value or key in fields:
            errors.append("duplicate_or_empty_field:" + key)
        else:
            fields[key] = value
    stage = fields.get("stage")
    if stage not in SCHEMA:
        errors.append("unknown_stage" if stage else "missing_stage")
    elif set(fields) - SCHEMA[stage]:
        errors.append("unknown_field:" + ",".join(sorted(set(fields) - SCHEMA[stage])))
    if stage in REQUIRED:
        missing = REQUIRED[stage] - set(fields)
        if missing:
            errors.append("missing_field:" + ",".join(sorted(missing)))
    if errors:
        return None, {"line": line_no, "raw": line.rstrip("\n"), "errors": errors}
    if stage in {"manager", "app"} and (fields.get("accepted") != "1" or fields.get("skip") != "0"):
        return None, {"line": line_no, "raw": line.rstrip("\n"), "errors": ["manager_app_requires_accepted_1_skip_0"]}
    parsed: dict[str, Any] = {"stage": stage, "line": line_no, "raw": line.rstrip("\n")}
    for key, value in fields.items():
        if key == "stage":
            parsed[key] = value
        elif key == "v":
            if value != "1":
                return None, {"line": line_no, "raw": line.rstrip("\n"), "errors": ["unsupported_version"]}
            parsed[key] = 1
        else:
            try:
                parsed[key] = _int(value, key)
            except ValueError as exc:
                errors.append(str(exc))
    if errors:
        return None, {"line": line_no, "raw": line.rstrip("\n"), "errors": errors}
    return parsed, None


def parse_diagnostics(text: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    malformed: list[dict[str, Any]] = []
    all_matched_lines: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        record, bad = _parse_line(line, line_no)
        if record is not None:
            records.append(record)
            all_matched_lines.append({"line": line_no, "raw": line, "valid": True})
        elif bad is not None:
            malformed.append(bad)
            all_matched_lines.append({"line": line_no, "raw": line, "valid": False, "errors": bad["errors"]})

    groups: dict[tuple[int, int], dict[str, Any]] = {}
    duplicates: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    result_headers: dict[int, dict[str, Any]] = {}
    truncations: list[dict[str, Any]] = []
    # A result announces its expected array slots. Seed those groups even
    # when no downstream interval record arrived.
    for record in records:
        if record.get("stage") == "result":
            if record["count"] > 4:
                truncations.append({"rid": record["rid"], "line": record["line"], "declared_count": record["count"], "seeded_count": 4})
            seed_count = min(max(record["count"], 0), 4)
            if record["count"] <= 0:
                seed_count = 1
            if record["wear"] == 0:
                seed_count = min(seed_count, 1)
            for index in range(seed_count):
                key = (record["rid"], index)
                group = groups.setdefault(key, {"rid": key[0], "index": key[1], "stages": {}, "stage_presence": [], "records": []})
                group["stages"]["result"] = record
                group["stage_presence"].append("result")
                group["records"].append(record)
            prior_result = result_headers.get(record["rid"])
            if prior_result is not None:
                duplicates.append({"rid": record["rid"], "stage": "result", "lines": [prior_result["line"], record["line"]]})
                left = {k: v for k, v in prior_result.items() if k not in {"line", "raw"}}
                right = {k: v for k, v in record.items() if k not in {"line", "raw"}}
                if left != right:
                    conflicts.append({"rid": record["rid"], "stage": "result", "lines": [prior_result["line"], record["line"]], "reason": "rid_reuse_or_wrap_ambiguity"})
            else:
                result_headers[record["rid"]] = record
    for record in records:
        if "rid" not in record or "index" not in record:
            continue
        key = (record["rid"], record["index"])
        group = groups.setdefault(key, {"rid": key[0], "index": key[1], "stages": {}, "stage_presence": [], "records": []})
        stage = record["stage"]
        prior = group["stages"].get(stage)
        if prior is not None:
            duplicates.append({"rid": key[0], "index": key[1], "stage": stage, "lines": [prior["line"], record["line"]]})
            comparable = {k: v for k, v in record.items() if k not in {"line", "raw", "clamps"}}
            old_comparable = {k: v for k, v in prior.items() if k not in {"line", "raw", "clamps"}}
            if comparable != old_comparable:
                conflicts.append({"rid": key[0], "index": key[1], "stage": stage, "lines": [prior["line"], record["line"]]})
        else:
            group["stages"][stage] = record
            group["stage_presence"].append(stage)
        group["records"].append(record)
    for group in groups.values():
        # A result header has no index. Associate it with every observed
        # interval key for this rid, including count=0 and count<0 headers.
        if "result" not in group["stages"] and group["rid"] in result_headers:
            group["stages"]["result"] = result_headers[group["rid"]]
            group["stage_presence"].append("result")
        group["stage_presence"] = sorted(set(group["stage_presence"]))
        group["stages"] = {k: v for k, v in group["stages"].items()}

    ticks = [(r["line"], r["stage"], r["ticks"]) for r in records if "ticks" in r]
    backwards = [{"from_line": a[0], "to_line": b[0], "from_ticks": a[2], "to_ticks": b[2]}
                 for a, b in zip(ticks, ticks[1:]) if b[2] < a[2]]
    return {
        "report": "ppi-diagnostics",
        "report_version": 1,
        "continuity_claim": None,
        "identity": "rid/index is an algorithm-result identity, never a beat ID",
        "ticks": "received firmware ticks; not beat timestamps",
        "matched_lines": records,
        "all_matched_lines": all_matched_lines,
        "malformed_ppi_diag": malformed,
        "groups": list(groups.values()),
        "duplicates": duplicates,
        "conflicts": conflicts,
        "missing_stage_evidence": [{"rid": g["rid"], "index": g["index"], "present": g["stage_presence"]}
                                    for g in groups.values()
                                    if not ({"result", "interval"} <= set(g["stage_presence"]))
                                    or ("interval" in g["stages"] and g["stages"]["interval"].get("accepted") == 1 and g["stages"]["interval"].get("skip") == 0
                                        and not {"manager", "app"} <= set(g["stage_presence"]))],
        "skips": [r for r in records if r.get("skip", 0) != 0 or r.get("accepted") == 0],
        "clamps": [],
        "truncated_result_count": truncations,
        "rid_reuse_or_wrap_ambiguity": [x for x in conflicts if x.get("reason") == "rid_reuse_or_wrap_ambiguity"],
        "tick_wrap_or_reset_ambiguity": backwards,
        "counts": {"matched": len(records), "malformed": len(malformed), "ordinary_ignored": max(0, len(text.splitlines()) - len(records) - len(malformed))},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = parse_diagnostics(args.input.read_text())
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    main()
