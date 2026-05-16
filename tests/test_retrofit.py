"""Retrofit: introspect an installed package + emit _biobabel/ skeleton."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 fallback — tomllib is stdlib only from 3.11
    import tomli as tomllib

from biobabel._retrofit.retrofit import retrofit_package


def _make_demo_pkg(root: Path, name: str = "demopkg") -> tuple[Path, Path]:
    """Build a minimal installable package layout inside *root*."""
    pkg_dir = root / name
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(
        textwrap.dedent(
            '''\
            """Demo package."""

            __all__ = ["estimate_size_factors", "plot_summary", "Helper"]


            def estimate_size_factors(adata, scale: float = 1.0) -> None:
                """Compute per-cell size factors and mutate adata.obs."""
                pass


            def plot_summary(adata, color_by: str = "leiden") -> None:
                """Render a summary plot."""
                pass


            class Helper:
                """A helper class."""
                pass
            '''
        ),
        encoding="utf-8",
    )
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent(
            f"""\
            [build-system]
            requires = ["hatchling"]
            build-backend = "hatchling.build"

            [project]
            name = "{name}"
            version = "0.1.0"
            requires-python = ">=3.10"
            """
        ),
        encoding="utf-8",
    )
    return pkg_dir, pyproject


@pytest.fixture
def demo_pkg(tmp_path, monkeypatch):
    pkg_dir, pyproject = _make_demo_pkg(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    # Force re-import in case other tests imported a previous demopkg.
    sys.modules.pop("demopkg", None)
    yield pkg_dir, pyproject
    sys.modules.pop("demopkg", None)


def test_retrofit_generates_expected_files(demo_pkg):
    pkg_dir, pyproject = demo_pkg
    result = retrofit_package(import_name="demopkg", contract_class="analysis")
    assert result.ok
    assert result.contract_class_guessed == "analysis"
    assert result.introspected_symbols >= 2  # excludes the class

    biobabel = pkg_dir / "_biobabel"
    assert (biobabel / "__init__.py").is_file()
    assert (biobabel / "package.yaml").is_file()
    assert (biobabel / "skill.md").is_file()
    assert not (biobabel / "r_translate.yaml").exists()  # removed per ADR-0005
    assert (biobabel / "examples" / "smoke.py").is_file()
    # functions/ generated for analysis class
    assert (biobabel / "functions" / "estimate_size_factors.yaml").is_file()
    assert (biobabel / "functions" / "plot_summary.yaml").is_file()
    # Helper is a class — not emitted as a function
    assert not (biobabel / "functions" / "Helper.yaml").exists()


def test_retrofit_refuses_when_biobabel_already_exists(demo_pkg):
    pkg_dir, _ = demo_pkg
    (pkg_dir / "_biobabel").mkdir()
    result = retrofit_package(import_name="demopkg")
    assert not result.ok
    assert "already exists" in result.error


def test_retrofit_dry_run_writes_nothing(demo_pkg):
    pkg_dir, _ = demo_pkg
    result = retrofit_package(import_name="demopkg", dry_run=True)
    assert result.ok
    assert not (pkg_dir / "_biobabel").exists()
    assert len(result.written_files) > 0  # would have written


def test_retrofit_patches_pyproject(demo_pkg):
    pkg_dir, pyproject = demo_pkg
    result = retrofit_package(import_name="demopkg", contract_class="analysis")
    assert result.ok
    assert result.pyproject_patched is True

    data = tomllib.loads(pyproject.read_text())
    assert data["tool"]["biobabel"]["contract_class"] == "analysis"
    entry_point = data["project"]["entry-points"]["biobabel.manifest"]["demopkg"]
    assert entry_point == "demopkg._biobabel:get_manifest"


def test_retrofit_guesses_analysis_for_adata_first_param(demo_pkg):
    result = retrofit_package(import_name="demopkg", dry_run=True)
    assert result.ok
    # All three public symbols take `adata` as first arg → should be analysis
    assert result.contract_class_guessed == "analysis"


def test_retrofit_unknown_import_returns_error(tmp_path):
    result = retrofit_package(import_name="this_package_does_not_exist_anywhere")
    assert not result.ok
    # `find_spec` returns None for missing packages → "no locatable __init__.py"
    assert (
        "no locatable" in result.error
        or "cannot find" in result.error
        or "cannot import" in result.error
    )


def test_retrofit_function_yaml_has_inspected_signature(demo_pkg):
    pkg_dir, _ = demo_pkg
    retrofit_package(import_name="demopkg", contract_class="analysis")
    fn_yaml = (pkg_dir / "_biobabel" / "functions" / "estimate_size_factors.yaml").read_text()
    assert "execution_class: adata_mutation" in fn_yaml
    assert "name: adata" in fn_yaml
    assert "name: scale" in fn_yaml
    assert "Compute per-cell size factors" in fn_yaml
