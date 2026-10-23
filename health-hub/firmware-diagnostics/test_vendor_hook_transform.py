import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

import vendor_hook_transform as transform


SOURCE_SUFFIX = Path(transform.PINNED_RELATIVE_PATH)


class VendorHookTransformTests(unittest.TestCase):
    def test_pinned_transform_is_idempotent(self):
        source = Path("/tmp/gravelex-goodix-research") / SOURCE_SUFFIX
        if not source.exists():
            self.skipTest("pinned Goodix checkout is not available")
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "hook.c"
            second = Path(tmp) / "hook-again.c"
            transform.transform(source, first)
            transform.transform(first, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).hexdigest(),
                transform.PATCHED_BLOB_SHA256,
            )

    def test_wrong_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / SOURCE_SUFFIX
            source.parent.mkdir(parents=True)
            source.write_text("wrong source\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                transform.transform(source, Path(tmp) / "out.c")

    def test_pinned_git_blob_hash_matches_record(self):
        source = Path("/tmp/gravelex-goodix-research") / SOURCE_SUFFIX
        if not source.exists():
            self.skipTest("pinned Goodix checkout is not available")
        blob = subprocess.check_output(
            [
                "git",
                "-C",
                "/tmp/gravelex-goodix-research",
                "show",
                transform.PINNED_COMMIT + ":" + transform.PINNED_RELATIVE_PATH,
            ]
        )
        self.assertEqual(hashlib.sha256(blob).hexdigest(), transform.PINNED_BLOB_SHA256)


if __name__ == "__main__":
    unittest.main()
