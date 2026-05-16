"""Contract validator against the real rgrid-python _biobabel/ directory."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from biobabel._contracts.validator import validate_package_dir

RGRID_BIOBABEL = Path(
    os.environ.get(
        "BIOBABEL_RGRID_DIR",
        "/home/groups/xiaojie/nianping/projects/tmp/agent_friendly/Bio-Babel-public/rgrid-python/grid_py/_biobabel",
    )
)


@pytest.mark.skipif(not RGRID_BIOBABEL.is_dir(), reason="rgrid-python _biobabel not available")
def test_rgrid_biobabel_validates():
    report = validate_package_dir(RGRID_BIOBABEL)
    if not report.ok:
        for issue in report.issues:
            print(f"{issue.severity:8s} {issue.code}: {issue.message}")
    assert report.ok, "rgrid-python _biobabel contract must validate"
    assert report.manifest is not None
    assert report.manifest.contract_class == "grammar"
    # Mandatory class-B fields populated
    assert report.manifest.concepts
    assert report.manifest.idioms
    assert report.manifest.anti_patterns


def test_missing_dir_reports_error(tmp_path):
    report = validate_package_dir(tmp_path / "does_not_exist")
    assert not report.ok
    assert any(i.code == "dir_missing" for i in report.issues)


def test_missing_package_yaml(tmp_path):
    biobabel = tmp_path / "_biobabel"
    biobabel.mkdir()
    report = validate_package_dir(biobabel)
    assert not report.ok
    assert any(i.code == "missing_package_yaml" for i in report.issues)
