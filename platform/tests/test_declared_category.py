"""The uploader's product choice must survive the round-trip through the manifest.

Runnable check for the declared-category path added to the upload flow:
    python -m tests.test_declared_category
"""
import json
import tempfile
from pathlib import Path

from etl.ingest import (MANIFEST, declared_ad_types, declared_categories,
                        declared_platforms, declared_sub_platforms)


def test_manifest_carries_category_and_platform():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "flipkart_aug.csv").write_text("x")
        (root / MANIFEST).write_text(json.dumps({
            "platform": "Flipkart", "category": "Filter Coffee",
            "sub_platform": "National", "ad_type": "PLA", "files": ["flipkart_aug.csv"],
        }))
        f = (root / "flipkart_aug.csv").resolve()
        assert declared_categories(root)[f] == "Filter Coffee"
        assert declared_platforms(root)[f] == "Flipkart"
        assert declared_sub_platforms(root)[f] == "National"
        assert declared_ad_types(root)[f] == "PLA"


def test_missing_category_is_absent_not_none():
    # An older manifest with only a platform must not inject a bogus category key.
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "f.csv").write_text("x")
        (root / MANIFEST).write_text(json.dumps({
            "platform": "Zepto", "files": ["f.csv"]}))
        assert declared_categories(root) == {}


if __name__ == "__main__":
    test_manifest_carries_category_and_platform()
    test_missing_category_is_absent_not_none()
    print("ok")
