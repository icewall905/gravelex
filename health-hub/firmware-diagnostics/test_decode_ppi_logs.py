from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from decode_ppi_logs import decode_lines, load_dictionary, _specifiers

ROOT = Path(__file__).resolve().parents[1]
ACTUAL_DICT = ROOT / "reference-data/firmware-diagnostics-20261023/fw/loghash_dict.json"

FIXTURE_MESSAGES = [
    "PPI_DIAG v=1 stage=result rid=%lu frame=%lu count=%ld confidence=%ld wear=%u ticks=%lu",
    "PPI_DIAG v=1 stage=interval rid=%lu index=%ld ppi=%hu quality=%d ticks=%lu accepted=1 skip=0",
    "PPI_DIAG v=1 stage=interval rid=%lu index=%ld ppi=%ld quality=%d ticks=%lu accepted=0 skip=%d",
    "PPI_DIAG v=1 stage=interval rid=%lu index=0 ppi=0 quality=%d ticks=%lu accepted=0 skip=2",
    "PPI_DIAG v=1 stage=interval rid=%lu index=0 ppi=0 quality=%d ticks=%lu accepted=1 skip=0",
    "PPI_DIAG v=1 stage=manager rid=%lu index=%hu ppi=%hu quality=%d ticks=%lu accepted=%hhu skip=0",
    "PPI_DIAG v=1 stage=app rid=%lu index=%hu ppi=%hu quality=%d ticks=%lu accepted=%hhu skip=0",
]


def actual_formats():
    dictionary = {str(index + 1): {"msg": message} for index, message in enumerate(FIXTURE_MESSAGES)}
    return dictionary


def test_actual_dictionary_has_seven_ppi_formats() -> None:
    dictionary = actual_formats()
    assert len(dictionary) == 7
    assert {entry["msg"].split()[2].split("=")[1] for entry in dictionary.values()} == {"result", "interval", "manager", "app"}


@pytest.mark.skipif(not ACTUAL_DICT.exists(), reason="private firmware dictionary unavailable")
def test_private_actual_dictionary_has_seven_ppi_formats() -> None:
    assert len(load_dictionary(ACTUAL_DICT)) == 7


def test_all_seven_actual_formats_decode_with_signed_and_unsigned_values() -> None:
    dictionary = actual_formats()
    lines = []
    for key, entry in dictionary.items():
        values = []
        for spec in _specifiers(entry["msg"]):
            values.append("FFFFFF9C" if spec in {"%ld", "%d"} else ("FFFFFFFF" if spec in {"%lu", "%u"} else ("FF" if spec == "%hhu" else "FFFF")))
        lines.append(f":0> NL:{int(key):x} {' '.join(values)}")
    decoded, stats = decode_lines("\n".join(lines), dictionary)
    assert len(decoded) == 7
    assert stats["skipped"] == 0
    assert any("rid=4294967295" in line for line in decoded)
    assert any("ppi=-100" in line for line in decoded)


def test_edge_values_include_u32_max_rid_and_tick_quality_minus_one() -> None:
    dictionary = actual_formats()
    entry = next(v for v in dictionary.values() if "stage=app" in v["msg"])
    key = next(k for k, v in dictionary.items() if v is entry)
    decoded, stats = decode_lines(f":0> NL:{int(key):x} FFFFFFFF 0000 03E8 FFFFFFFF FFFFFFFF FF", dictionary)
    assert stats["decoded"] == 1
    assert "rid=4294967295" in decoded[0] and "quality=-1" in decoded[0]


def test_unknown_hash_truncated_and_malformed_arguments_are_skipped() -> None:
    dictionary = actual_formats()
    key, entry = next(iter(dictionary.items()))
    good = f":0> NL:{int(key):x} " + " ".join("0" for _ in range(len(entry["msg"].split("%")) - 1))
    text = "\n".join([good, ":0> NL:deadbeef 0", ":0> NL:" + format(int(key), "x") + " nothex"])
    decoded, stats = decode_lines(text, dictionary)
    assert stats["decoded"] == 1 and stats["skipped"] == 2


def test_wrong_dictionary_is_rejected() -> None:
    raw = json.loads(json.dumps(actual_formats()))
    ppi_key = next(k for k, v in raw.items() if isinstance(v, dict) and "PPI_DIAG" in v.get("msg", ""))
    raw.pop(ppi_key)
    path = Path(__file__).with_name(".tmp-wrong-loghash.json")
    path.write_text(json.dumps(raw))
    try:
        with pytest.raises(ValueError):
            load_dictionary(path)
    finally:
        path.unlink()


@pytest.mark.parametrize("message", [
    "PPI_DIAG v=1 stage=result rid=%s frame=%lu count=%ld confidence=%ld wear=%u ticks=%lu",
    "PPI_DIAG v=1 stage=result rid=%lu frame=%lu count=%ld confidence=%ld wear=%u ticks=%lu %",
])
def test_unsupported_or_malformed_ppi_format_is_rejected(message: str) -> None:
    raw = json.loads(json.dumps(actual_formats()))
    raw["999"] = {"msg": message}
    path = Path(__file__).with_name(".tmp-invalid-loghash.json")
    path.write_text(json.dumps(raw))
    try:
        with pytest.raises(ValueError):
            load_dictionary(path)
    finally:
        path.unlink()


def test_duplicate_ppi_format_is_rejected() -> None:
    raw = json.loads(json.dumps(actual_formats()))
    raw["999"] = {"msg": next(iter(raw.values()))["msg"]}
    path = Path(__file__).with_name(".tmp-duplicate-loghash.json")
    path.write_text(json.dumps(raw))
    try:
        with pytest.raises(ValueError):
            load_dictionary(path)
    finally:
        path.unlink()


def test_cli_is_offline_exclusive_0600_and_outputs_only_ppi(tmp_path: Path) -> None:
    source = tmp_path / "capture.log"
    output = tmp_path / "decoded.log"
    key, entry = next(iter(actual_formats().items()))
    args = " ".join("0" for _ in range(len(entry["msg"].split("%")) - 1))
    source.write_text("ordinary line\n:0> NL:" + format(int(key), "x") + " " + args + "\n")
    script = Path(__file__).with_name("decode_ppi_logs.py")
    dictionary = tmp_path / "dict.json"
    dictionary.write_text(json.dumps(actual_formats()))
    subprocess.run(["python3", str(script), str(source), str(dictionary), str(output)], check=True, capture_output=True)
    before = output.read_bytes()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert b"PPI_DIAG" in before and b"ordinary" not in before
    second = subprocess.run(["python3", str(script), str(source), str(dictionary), str(output)], capture_output=True)
    assert second.returncode != 0 and output.read_bytes() == before
