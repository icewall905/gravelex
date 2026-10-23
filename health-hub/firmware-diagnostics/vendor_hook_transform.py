#!/usr/bin/env python3
"""Transform exactly the pinned Goodix HRV hook; never fetch, flash, or bundle vendor code."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


PINNED_COMMIT = "d8ce9fc9bcc527094554bffc00822fb24d7907c1"
PINNED_RELATIVE_PATH = (
    "gh3x2x/demo_code/demo_algo_code/goodix_algo_application/src/"
    "gh3x2x_demo_algo_hook.c"
)
PINNED_BLOB_SHA256 = "e0720f67547a5d5ee2c7c2735072cb99b47a753f7d680e54b2c06520c570b460"
PATCHED_BLOB_SHA256 = "b4fb7e5e029742cd05120e281c71586517b3b207bfa1a1c8d795c9ff7eb6be54"
MARKER = "/* PPI_DIAG_VENDOR_HOOK_V1 */"

OLD = """    UNUSED_VAR(lubFrameId);\n#if (__USE_GOODIX_HRV_ALGORITHM__) && defined(CONFIG_HRM_HRV)\n    /* code implement by user */\n    extern void gh3x2x_hrv_result_report(const int32_t *rri, int32_t confidence, int32_t valid_num);\n    gh3x2x_hrv_result_report((const int32_t *)&pstAlgoResult->snResult[0],\n                             pstAlgoResult->snResult[4],\n                             pstAlgoResult->snResult[5]);\n#else\n    UNUSED_VAR(pstAlgoResult);\n#endif\n"""

NEW = """    /* PPI_DIAG_VENDOR_HOOK_V1 */\n#if (__USE_GOODIX_HRV_ALGORITHM__) && defined(CONFIG_HRM_HRV)\n#if defined(CONFIG_HRM_PPI_DIAGNOSTICS)\n    extern void gh3x2x_hrv_diag_bridge(const int32_t *rri, int32_t confidence,\n                                        int32_t valid_num, uint32_t frame_id);\n    gh3x2x_hrv_diag_bridge((const int32_t *)&pstAlgoResult->snResult[0],\n                           pstAlgoResult->snResult[4],\n                           pstAlgoResult->snResult[5], lubFrameId);\n#else\n    extern void gh3x2x_hrv_result_report(const int32_t *rri, int32_t confidence, int32_t valid_num);\n    gh3x2x_hrv_result_report((const int32_t *)&pstAlgoResult->snResult[0],\n                             pstAlgoResult->snResult[4],\n                             pstAlgoResult->snResult[5]);\n#endif\n#else\n    UNUSED_VAR(pstAlgoResult);\n    UNUSED_VAR(lubFrameId);\n#endif\n"""


def transform(source: Path, destination: Path) -> None:
    data = source.read_bytes()
    text = data.decode("utf-8")
    old_bytes = OLD.replace("\n", "\r\n").encode("utf-8")
    new_bytes = NEW.replace("\n", "\r\n").encode("utf-8")
    if MARKER in text:
        if OLD in text or "gh3x2x_hrv_diag_bridge" not in text:
            raise SystemExit("refusing inconsistent partially transformed source")
        if PATCHED_BLOB_SHA256 and hashlib.sha256(data).hexdigest() != PATCHED_BLOB_SHA256:
            raise SystemExit("refusing transformed source with an unexpected blob hash")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return
    if not source.as_posix().endswith(PINNED_RELATIVE_PATH):
        raise SystemExit(f"refusing source: expected pinned path suffix {PINNED_RELATIVE_PATH}")
    digest = hashlib.sha256(data).hexdigest()
    if digest != PINNED_BLOB_SHA256:
        raise SystemExit(
            f"refusing source: sha256={digest}, expected pinned Goodix blob {PINNED_BLOB_SHA256}"
        )
    if data.count(old_bytes) != 1:
        raise SystemExit("refusing source: expected exactly one HRV hook body")
    destination.parent.mkdir(parents=True, exist_ok=True)
    transformed = data.replace(old_bytes, new_bytes, 1)
    if PATCHED_BLOB_SHA256 and hashlib.sha256(transformed).hexdigest() != PATCHED_BLOB_SHA256:
        raise SystemExit("refusing generated source with an unexpected blob hash")
    destination.write_bytes(transformed)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    transform(args.source, args.destination)


if __name__ == "__main__":
    main()
