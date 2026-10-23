#!/usr/bin/env python3
"""Offline decoder for hashed PPI_DIAG lines using an exact build dictionary."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

LINE_RE = re.compile(r"(?<![A-Za-z0-9_]):0>\s+NL:([0-9A-Fa-f]+)(?:\s+(.*))?$")
SUPPORTED = {"%lu", "%ld", "%hu", "%hhu", "%d", "%u"}
PPI_PREFIX = "PPI_DIAG "
EXPECTED_MESSAGES = {
    "PPI_DIAG v=1 stage=result rid=%lu frame=%lu count=%ld confidence=%ld wear=%u ticks=%lu",
    "PPI_DIAG v=1 stage=interval rid=%lu index=%ld ppi=%hu quality=%d ticks=%lu accepted=1 skip=0",
    "PPI_DIAG v=1 stage=interval rid=%lu index=%ld ppi=%ld quality=%d ticks=%lu accepted=0 skip=%d",
    "PPI_DIAG v=1 stage=interval rid=%lu index=0 ppi=0 quality=%d ticks=%lu accepted=0 skip=2",
    "PPI_DIAG v=1 stage=interval rid=%lu index=0 ppi=0 quality=%d ticks=%lu accepted=1 skip=0",
    "PPI_DIAG v=1 stage=manager rid=%lu index=%hu ppi=%hu quality=%d ticks=%lu accepted=%hhu skip=0",
    "PPI_DIAG v=1 stage=app rid=%lu index=%hu ppi=%hu quality=%d ticks=%lu accepted=%hhu skip=0",
}


def _specifiers(message: str) -> list[str]:
    found = re.findall(r"%(?:l[ud]|hh[ud]|h[ud]|[ud])", message)
    return found


def _decode_arg(token: str, spec: str) -> int:
    if not re.fullmatch(r"(?:0x)?[0-9A-Fa-f]+", token):
        raise ValueError("argument is not hexadecimal")
    raw = int(token, 16)
    widths = {"%hhu": 8, "%hu": 16, "%lu": 32, "%u": 32, "%ld": 32, "%d": 32}
    width = widths[spec]
    if raw > (1 << width) - 1:
        raise ValueError(f"{spec} argument exceeds {width}-bit range")
    if spec in {"%ld", "%d"} and raw >= 1 << (width - 1):
        return raw - (1 << width)
    return raw


def _format_message(message: str, values: list[int]) -> str:
    specs = _specifiers(message)
    out: list[str] = []
    pos = 0
    for value, spec in zip(values, specs):
        at = message.index(spec, pos)
        out.append(message[pos:at])
        out.append(str(value))
        pos = at + len(spec)
    out.append(message[pos:])
    return "".join(out)


def load_dictionary(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
        raise ValueError("dictionary must be an object")
    selected: dict[str, dict[str, Any]] = {}
    seen_messages: set[str] = set()
    for key, entry in raw.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("msg"), str):
            continue
        message = entry["msg"]
        specs = _specifiers(message)
        if message.startswith(PPI_PREFIX) and message not in EXPECTED_MESSAGES:
            raise ValueError("unsupported or malformed PPI_DIAG dictionary format")
        if message.startswith(PPI_PREFIX) and message in EXPECTED_MESSAGES:
            if message in seen_messages:
                raise ValueError("duplicate PPI_DIAG dictionary format")
            seen_messages.add(message)
            selected[str(key)] = entry
    if len(selected) != 7 or seen_messages != EXPECTED_MESSAGES:
        raise ValueError(f"expected exactly seven PPI_DIAG dictionary formats, found {len(selected)}")
    return selected


def decode_lines(text: str, dictionary: dict[str, dict[str, Any]]) -> tuple[list[str], dict[str, int]]:
    output: list[str] = []
    stats = {"input_lines": 0, "hashed_lines": 0, "decoded": 0, "skipped": 0}
    for line in text.splitlines():
        stats["input_lines"] += 1
        match = LINE_RE.search(line.strip())
        if not match:
            continue
        stats["hashed_lines"] += 1
        key, arg_text = match.group(1), match.group(2) or ""
        entry = dictionary.get(str(int(key, 16)))
        if entry is None:
            stats["skipped"] += 1
            continue
        message = entry["msg"]
        specs = _specifiers(message)
        args = arg_text.split()
        if len(args) != len(specs):
            stats["skipped"] += 1
            continue
        try:
            values = [_decode_arg(token, spec) for token, spec in zip(args, specs)]
            decoded = _format_message(message, values)
        except (ValueError, KeyError):
            stats["skipped"] += 1
            continue
        output.append(decoded)
        stats["decoded"] += 1
    return output, stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("dictionary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    dictionary = load_dictionary(args.dictionary)
    decoded, stats = decode_lines(args.input.read_text(), dictionary)
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(decoded))
        if decoded:
            stream.write("\n")
    print(json.dumps(stats, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    main()
