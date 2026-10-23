from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from parse_ppi_diagnostics import parse_diagnostics


def line(stage: str, rid: int = 7, index: int = 0, ticks: int = 100) -> str:
    if stage == "result":
        return f"PPI_DIAG v=1 stage=result rid={rid} frame=22 count=2 confidence=80 wear=1 ticks={ticks}"
    if stage == "interval":
        return f"PPI_DIAG v=1 stage=interval rid={rid} frame=22 index={index} ppi=900 quality=2 ticks={ticks} accepted=1 skip=0"
    return f"PPI_DIAG v=1 stage={stage} rid={rid} index={index} ppi=900 quality=2 ticks={ticks} accepted=1 skip=0"


def test_full_result_two_ppis_keeps_order_and_identity() -> None:
    text = "ordinary\n" + "\n".join([line("result"), line("interval", index=0), line("manager", index=0), line("app", index=0),
                                           line("interval", index=1, ticks=101), line("manager", index=1, ticks=101)])
    result = parse_diagnostics(text)
    assert [row["line"] for row in result["matched_lines"]] == [2, 3, 4, 5, 6, 7]
    assert [(g["rid"], g["index"]) for g in result["groups"]] == [(7, 0), (7, 1)]
    assert result["continuity_claim"] is None
    assert result["identity"].startswith("rid/index")


def test_duplicates_and_conflicts_are_preserved() -> None:
    result = parse_diagnostics(line("interval") + "\n" + line("interval"))
    assert len(result["matched_lines"]) == 2
    assert len(result["duplicates"]) == 1
    assert result["conflicts"] == []
    result = parse_diagnostics(line("interval") + "\n" + line("interval", ticks=101))
    assert len(result["conflicts"]) == 1


def test_missing_stage_malformed_and_boolean_string_are_visible() -> None:
    text = "\n".join([
        line("result"),
        "PPI_DIAG v=1 stage=manager rid=7 index=0 ppi=900 skip=0 ticks=100 accepted=1",
        "PPI_DIAG v=1 stage=manager rid=7 index=0 ppi=true quality=2 ticks=100 accepted=1 skip=0",
        "PPI_DIAG v=1 stage=wat rid=7 index=0 ppi=900 quality=2 ticks=100",
    ])
    result = parse_diagnostics(text)
    assert len(result["malformed_ppi_diag"]) == 3
    assert any("missing_field" in e for e in result["malformed_ppi_diag"][0]["errors"])
    assert any("decimal integer" in e for e in result["malformed_ppi_diag"][1]["errors"])
    assert any("unknown_stage" in e for e in result["malformed_ppi_diag"][2]["errors"])
    assert result["missing_stage_evidence"]


def test_out_of_range_values_are_clamped_and_tick_backwards_is_ambiguous() -> None:
    text = line("interval", ticks=10) + "\n" + line("interval", ticks=2)
    text += "\n" + line("interval", ticks=3).replace("ppi=900", "ppi=99999999999")
    result = parse_diagnostics(text)
    assert len(result["clamps"]) == 0
    assert len(result["malformed_ppi_diag"]) == 1
    assert result["tick_wrap_or_reset_ambiguity"]
    assert result["continuity_claim"] is None


def test_cli_output_is_exclusive_600_and_does_not_modify_input(tmp_path: Path) -> None:
    source = tmp_path / "capture.log"
    output = tmp_path / "result.json"
    original = ("noise\n" + line("result") + "\n").encode()
    source.write_bytes(original)
    script = Path(__file__).with_name("parse_ppi_diagnostics.py")
    subprocess.run(["python3", str(script), str(source), str(output)], check=True)
    before = output.read_bytes()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(before)["counts"]["matched"] == 1
    assert source.read_bytes() == original
    second = subprocess.run(["python3", str(script), str(source), str(output)], capture_output=True)
    assert second.returncode != 0
    assert output.read_bytes() == before


def test_unsigned_ids_and_ticks_reject_negative_values() -> None:
    result = parse_diagnostics(line("result", rid=-1).replace("rid=-1", "rid=-1"))
    assert not result["matched_lines"]
    assert result["malformed_ppi_diag"]


def test_result_count_over_four_is_reported_and_bounded() -> None:
    text = line("result").replace("count=2", "count=9")
    result = parse_diagnostics(text)
    assert result["truncated_result_count"][0]["declared_count"] == 9
    assert len(result["groups"]) == 4


def test_interval_signed_ppi_is_preserved_and_skip_is_reported() -> None:
    text = line("interval").replace("ppi=900", "ppi=-900").replace("skip=0", "skip=2")
    result = parse_diagnostics(text)
    assert result["matched_lines"][0]["ppi"] == -900
    assert result["skips"][0]["skip"] == 2


def test_zero_and_negative_result_counts_attach_header_to_observed_interval() -> None:
    for count in (0, -1):
        text = line("result").replace("count=2", f"count={count}") + "\n" + line("interval")
        result = parse_diagnostics(text)
        assert len(result["groups"]) == 1
        assert "result" in result["groups"][0]["stage_presence"]


def test_nonpositive_result_count_seeds_index_zero_sentinel() -> None:
    for count in (0, -1):
        result = parse_diagnostics(line("result").replace("count=2", f"count={count}"))
        assert [(g["rid"], g["index"]) for g in result["groups"]] == [(7, 0)]
        assert result["missing_stage_evidence"]


def test_off_wrist_result_seeds_only_slot_zero() -> None:
    text = line("result").replace("wear=1", "wear=0") + "\n" + line("interval")
    result = parse_diagnostics(text)
    assert [(g["rid"], g["index"]) for g in result["groups"]] == [(7, 0)]


def test_uint32_boundaries_are_accepted() -> None:
    text = line("result", rid=4294967295, ticks=4294967295).replace("frame=22", "frame=4294967295")
    result = parse_diagnostics(text)
    assert result["matched_lines"][0]["rid"] == 4294967295
