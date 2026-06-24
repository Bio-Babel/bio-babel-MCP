"""Retrofit: introspect an existing installed Python package, generate a
half-filled `_biobabel/` directory, and additively patch pyproject.toml.

Important: this is *scaffold-time* introspection (one-shot, output is YAML on
disk for humans to review). It is **not** runtime reflection — biobabel still
only reads the (then-edited) YAML at MCP-server-time. The hard constraint
"no reflection fallback" applies at runtime; using inspect to *generate a stub
for the human* is a legitimate dev tool.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import inspect
import textwrap
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
import yaml


@dataclass
class RetrofitResult:
    ok: bool
    package_root: Path | None = None
    biobabel_dir: Path | None = None
    pyproject_path: Path | None = None
    pyproject_patched: bool = False
    written_files: list[Path] = field(default_factory=list)
    introspected_symbols: int = 0
    skipped_symbols: list[str] = field(default_factory=list)
    contract_class_guessed: str = ""
    todos: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""


# Heuristics for symbol behavior / contract_class.
# Producers always review the generated YAML, so these are best-effort
# defaults — wrong guesses cost a single edit, not a regression.
_ADATA_NAMES = {"adata", "anndata", "cds"}
_DF_NAMES = {"df", "dataframe"}
_PLOT_PREFIXES = ("plot_", "vis_", "draw_")
# Above this fraction of adata-mutating functions, default contract_class
# to "analysis". Below, prefer "grammar" if there are enough plot helpers.
_ANALYSIS_HEURISTIC_RATIO = 0.3
_GRAMMAR_PLOT_COUNT = 3


def retrofit_package(
    *,
    import_name: str,
    contract_class: str | None = None,
    r_package: str | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> RetrofitResult:
    # First, locate the package source tree WITHOUT importing (works even if
    # the package's top-level import fails due to a missing C-extension dep).
    try:
        spec = importlib.util.find_spec(import_name)
    except (ImportError, ValueError) as exc:
        return RetrofitResult(ok=False, error=f"cannot find '{import_name}': {exc}")
    if spec is None or spec.origin is None:
        return RetrofitResult(
            ok=False,
            error=(
                f"'{import_name}' has no locatable __init__.py "
                f"(namespace package?); cannot retrofit."
            ),
        )

    package_root = Path(spec.origin).parent.resolve()
    biobabel_dir = package_root / "_biobabel"

    if biobabel_dir.exists() and not force:
        return RetrofitResult(
            ok=False,
            package_root=package_root,
            biobabel_dir=biobabel_dir,
            error=(
                f"_biobabel/ already exists at {biobabel_dir}. "
                "Pass --force to overwrite (your edits will be lost)."
            ),
        )

    # Find pyproject.toml — walk up from the package root.
    pyproject_path = _find_pyproject(package_root)

    # Two-phase introspection: try the cheap "fully import" path first;
    # if that fails (heavy C-ext deps unavailable in this env), fall back to
    # AST-driven per-submodule introspection that emits stubs for unreachable
    # submodules instead of failing the whole retrofit.
    warnings: list[str] = []
    skipped: list[str] = []
    symbols, fallback_warnings, fallback_skipped = _introspect_robust(
        import_name, package_root
    )
    warnings.extend(fallback_warnings)
    skipped.extend(fallback_skipped)

    # Guess contract_class if not provided.
    if contract_class is None:
        contract_class = _guess_contract_class(symbols)

    # Build the file plan.
    plan = _build_plan(
        import_name=import_name,
        package_root=package_root,
        biobabel_dir=biobabel_dir,
        contract_class=contract_class,
        r_package=r_package,
        symbols=symbols,
    )

    if dry_run:
        return RetrofitResult(
            ok=True,
            package_root=package_root,
            biobabel_dir=biobabel_dir,
            pyproject_path=pyproject_path,
            pyproject_patched=False,
            written_files=list(plan.keys()),
            introspected_symbols=len(symbols),
            skipped_symbols=skipped,
            contract_class_guessed=contract_class,
            todos=_build_todos(symbols, contract_class, pyproject_path is not None),
            warnings=warnings,
        )

    # Write.
    biobabel_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path, content in plan.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)

    # Patch pyproject.toml.
    pyproject_patched = False
    if pyproject_path is not None:
        pyproject_patched = _patch_pyproject(pyproject_path, import_name, contract_class)

    return RetrofitResult(
        ok=True,
        package_root=package_root,
        biobabel_dir=biobabel_dir,
        pyproject_path=pyproject_path,
        pyproject_patched=pyproject_patched,
        written_files=written,
        introspected_symbols=len(symbols),
        skipped_symbols=skipped,
        contract_class_guessed=contract_class,
        todos=_build_todos(symbols, contract_class, pyproject_path is not None),
        warnings=warnings,
    )


# --- Introspection -------------------------------------------------------


@dataclass
class SymbolInfo:
    name: str
    qual_name: str               # e.g. "<import_name>.<function_name>"
    signature: str
    parameters: list[dict[str, Any]]
    return_annotation: str
    docstring: str
    is_class: bool
    behavior_guess: str          # "plain_call" | "adata_mutation" | ...


def _introspect_robust(
    import_name: str, package_root: Path
) -> tuple[list[SymbolInfo], list[str], list[str]]:
    """Return (symbols, warnings, skipped_names).

    Strategy:
      1. Try to import the top-level package. If it works, introspect normally.
      2. If import fails, AST-parse the package's __init__.py to recover the
         `from .submod import name1, name2` map and `__all__`. Then import each
         submodule individually. Submodules that still fail (heavy C-ext deps
         unavailable) produce stub SymbolInfo entries with no signatures.
    """
    warnings: list[str] = []
    skipped: list[str] = []

    try:
        mod = importlib.import_module(import_name)
        return _introspect_imported(mod), warnings, skipped
    except Exception as exc:  # noqa: BLE001 — any import-time failure
        warnings.append(
            f"top-level import of {import_name!r} failed ({type(exc).__name__}: {exc}); "
            f"falling back to AST-driven per-submodule introspection."
        )

    init_path = package_root / "__init__.py"
    if not init_path.is_file():
        warnings.append(f"no __init__.py at {init_path}; no symbols introspected")
        return [], warnings, skipped

    submod_to_names, all_names = _parse_init_imports(init_path)

    out: list[SymbolInfo] = []
    for submod, names in submod_to_names.items():
        full_submod = f"{import_name}.{submod}"
        try:
            sub = importlib.import_module(full_submod)
        except Exception as exc:  # noqa: BLE001
            warnings.append(
                f"submodule {full_submod} unavailable "
                f"({type(exc).__name__}: {exc}); emitted stubs for: {', '.join(sorted(names))}"
            )
            for name in sorted(names):
                if all_names and name not in all_names:
                    continue
                skipped.append(name)
                out.append(_stub_symbol(name, full_submod))
            continue

        for name in sorted(names):
            if all_names and name not in all_names:
                continue
            obj = getattr(sub, name, None)
            if obj is None or inspect.ismodule(obj):
                continue
            if not (inspect.isfunction(obj) or inspect.isbuiltin(obj) or inspect.isclass(obj)):
                continue
            out.append(_describe(name, obj, import_name))

    out.sort(key=lambda s: s.name)
    return out, warnings, skipped


def _introspect_imported(mod: Any) -> list[SymbolInfo]:
    names = getattr(mod, "__all__", None)
    if names is None:
        names = [n for n in dir(mod) if not n.startswith("_")]

    out: list[SymbolInfo] = []
    for name in names:
        obj = getattr(mod, name, None)
        if obj is None:
            continue
        if inspect.ismodule(obj):
            continue
        if not (inspect.isfunction(obj) or inspect.isbuiltin(obj) or inspect.isclass(obj)):
            continue
        obj_module = getattr(obj, "__module__", "")
        if not obj_module.startswith(mod.__name__):
            continue
        out.append(_describe(name, obj, mod.__name__))
    out.sort(key=lambda s: s.name)
    return out


def _parse_init_imports(init_path: Path) -> tuple[dict[str, set[str]], set[str]]:
    """AST-extract `from .submod import name1, name2` and `__all__` without executing."""
    source = init_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    submod_to_names: dict[str, set[str]] = {}
    all_names: set[str] = set()

    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            names = {alias.asname or alias.name for alias in node.names if alias.name != "*"}
            submod_to_names.setdefault(node.module, set()).update(names)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    value = node.value
                    if isinstance(value, (ast.List, ast.Tuple)):
                        for elt in value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                all_names.add(elt.value)

    return submod_to_names, all_names


def _stub_symbol(name: str, submod_qual: str) -> SymbolInfo:
    """Symbol we know exists (from __init__.py) but cannot introspect (submodule import failed)."""
    return SymbolInfo(
        name=name,
        qual_name=f"{submod_qual}.{name}",
        signature="",
        parameters=[],
        return_annotation="",
        docstring="(submodule import failed; signature could not be introspected — fill manually)",
        is_class=False,
        behavior_guess="plain_call",
    )


def _describe(name: str, obj: Callable[..., Any], pkg_name: str) -> SymbolInfo:
    params: list[dict[str, Any]] = []
    return_anno = ""
    signature = ""
    try:
        sig = inspect.signature(obj)
        signature = f"{name}{sig}"
        for pname, p in sig.parameters.items():
            params.append(
                {
                    "name": pname,
                    "type": _annotation_str(p.annotation),
                    "required": p.default is inspect.Parameter.empty,
                    "default": _default_repr(p.default),
                }
            )
        return_anno = _annotation_str(sig.return_annotation)
    except (TypeError, ValueError):
        # builtins or C-extension callables without inspectable signatures
        pass

    docstring = inspect.getdoc(obj) or ""
    guess = _guess_symbol_behavior(name, params)

    return SymbolInfo(
        name=name,
        qual_name=f"{pkg_name}.{name}",
        signature=signature,
        parameters=params,
        return_annotation=return_anno,
        docstring=docstring,
        is_class=inspect.isclass(obj),
        behavior_guess=guess,
    )


def _annotation_str(anno: Any) -> str:
    if anno is inspect.Parameter.empty or anno is inspect.Signature.empty:
        return ""
    if hasattr(anno, "__name__"):
        return anno.__name__
    return str(anno).replace("typing.", "")


def _default_repr(default: Any) -> Any:
    if default is inspect.Parameter.empty:
        return None
    if isinstance(default, (str, int, float, bool, type(None))):
        return default
    return repr(default)


def _guess_symbol_behavior(name: str, params: list[dict[str, Any]]) -> str:
    if name.startswith(_PLOT_PREFIXES):
        return "plot"
    if not params:
        return "plain_call"
    first = params[0]["name"].lower()
    first_type = (params[0].get("type") or "").lower()
    if first in _ADATA_NAMES or "anndata" in first_type or "cds" in first_type:
        return "adata_mutation"
    if first in _DF_NAMES or "dataframe" in first_type:
        return "dataframe_mutation"
    return "plain_call"


def _guess_contract_class(symbols: list[SymbolInfo]) -> str:
    """Heuristic from the mix of guessed symbol behaviors.

    "analysis" wins when adata-mutating functions are common; "grammar"
    wins when there are enough plot helpers and few adata mutators.
    "analysis" is the safer default — producer can override with --class.
    """
    if not symbols:
        return "analysis"
    adata_like = sum(1 for s in symbols if s.behavior_guess == "adata_mutation")
    plot_like = sum(1 for s in symbols if s.behavior_guess == "plot")
    ratio = adata_like / len(symbols)
    if ratio >= _ANALYSIS_HEURISTIC_RATIO:
        return "analysis"
    if plot_like >= _GRAMMAR_PLOT_COUNT:
        return "grammar"
    return "analysis"


# --- File generation -----------------------------------------------------


def _build_plan(
    *,
    import_name: str,
    package_root: Path,
    biobabel_dir: Path,
    contract_class: str,
    r_package: str | None,
    symbols: list[SymbolInfo],
) -> dict[Path, str]:
    plan: dict[Path, str] = {}

    plan[biobabel_dir / "__init__.py"] = _INIT_PY_TEMPLATE
    plan[biobabel_dir / "package.yaml"] = _render_package_yaml(
        import_name, contract_class, r_package, package_root
    )
    plan[biobabel_dir / "skill.md"] = _render_skill_md(import_name)
    plan[biobabel_dir / "examples" / "smoke.py"] = _render_smoke_py(import_name)
    plan[biobabel_dir / "templates" / "README_TODO.md"] = _render_templates_todo(import_name)

    public_symbols = [s for s in symbols if s.name and not s.name.startswith("_")]
    if public_symbols:
        for s in public_symbols:
            plan[biobabel_dir / "symbols" / f"{s.name}.yaml"] = _render_symbol_yaml(s, import_name)
    else:
        plan[biobabel_dir / "symbols" / "README_TODO.md"] = (
            "# symbols/\n\n"
            "TODO: add SymbolContract YAML files for the public APIs an agent should call.\n"
        )

    if contract_class in ("analysis", "mixed"):
        plan[biobabel_dir / "workflows" / "README_TODO.md"] = (
            "# workflows/\n\n"
            "TODO: add WorkflowContract YAML files for canonical multi-step analyses.\n"
            "Delete this file if the package only exposes independent symbols.\n"
        )

    if contract_class in ("grammar", "mixed"):
        # Leave concepts/idioms/anti_patterns/ empty TODO directories — these
        # need genuine human judgement, not introspection.
        plan[biobabel_dir / "concepts" / "README_TODO.md"] = (
            "# concepts/\n\n"
            "TODO: add at least one ConceptSpec yaml describing a core mental model.\n"
            "Each file: see docs/architecture.md for the schema.\n"
        )
        plan[biobabel_dir / "idioms" / "README_TODO.md"] = (
            "# idioms/\n\nTODO: add at least one IdiomSpec yaml.\n"
        )
        plan[biobabel_dir / "anti_patterns" / "README_TODO.md"] = (
            "# anti_patterns/\n\nTODO: add at least one AntiPatternSpec yaml.\n"
        )

    return plan


# Static template — no parameter substitution, so it lives as a module
# constant rather than a function. The generated _biobabel/__init__.py is
# byte-identical across all packages.
_INIT_PY_TEMPLATE = textwrap.dedent('''\
    """biobabel manifest factory.

    Loads the YAML files in this directory and validates them via Pydantic.
    Wired into pyproject.toml as the `biobabel.manifest` entry point.
    """

    from __future__ import annotations

    from pathlib import Path

    import yaml

    from biobabel.manifest_api import PackageManifest

    _HERE = Path(__file__).parent


    def get_manifest() -> PackageManifest:
        data = yaml.safe_load((_HERE / "package.yaml").read_text(encoding="utf-8")) or {}

        for subdir, field in (
            ("symbols", "symbols"),
            ("workflows", "workflows"),
            ("templates", "templates"),
            ("concepts", "concepts"),
            ("idioms", "idioms"),
            ("anti_patterns", "anti_patterns"),
            ("compositions", "compositions"),
        ):
            items = list(data.get(field, []) or [])
            for yfile in sorted((_HERE / subdir).glob("*.yaml")):
                loaded = yaml.safe_load(yfile.read_text(encoding="utf-8"))
                if loaded is None:
                    continue
                if isinstance(loaded, list):
                    items.extend(loaded)
                else:
                    items.append(loaded)
            if items:
                data[field] = items

        return PackageManifest.model_validate(data)
    ''')


def _render_package_yaml(
    import_name: str, contract_class: str, r_package: str | None, package_root: Path
) -> str:
    data: dict[str, Any] = {
        "schema_version": 1,
        "repo": "TODO: https://github.com/<org>/<repo>",
        "distribution": "TODO: <pypi-distribution-name>",
        "import_name": import_name,
        "display_name": f"TODO: {import_name} display name",
        "contract_class": contract_class,
        "tier": 3,
        "maturity": "alpha",
        "foundation": [],
    }
    if r_package:
        data["r_package"] = {
            "package": r_package,
            "repo": "TODO",
            "version_or_commit": "TODO",
            "fidelity": "partial",
        }
    header = (
        "# Generated by `biobabel new contract`.\n"
        "# Fields tagged TODO must be filled before this contract is useful.\n"
        "# Run `biobabel validate package --pkg " + import_name + " --strict` after editing.\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _render_skill_md(import_name: str) -> str:
    return textwrap.dedent(f"""\
        ---
        name: use-{import_name.replace("_", "-")}
        description: TODO — one-sentence description of when an agent should reach for {import_name}.
        ---

        # {import_name}

        TODO: write a 30-second mental-model section explaining the central
        abstractions, the invariants, and the cardinal idioms an agent must know
        to use this package correctly.

        ## Quick reference

        TODO: minimal working example.

        For more: `biobabel.describe_package(import_name="{import_name}")`.
        """)


def _render_smoke_py(import_name: str) -> str:
    return textwrap.dedent(f'''\
        """Smoke test for {import_name}._biobabel.

        Generated by `biobabel new contract`. Edit to actually exercise the package's
        public API (this template only verifies importability).
        """

        from __future__ import annotations


        def main() -> None:
            import {import_name}  # noqa: F401
            print("imported {import_name} successfully")


        if __name__ == "__main__":
            main()
        ''')


def _render_templates_todo(import_name: str) -> str:
    return textwrap.dedent(f"""\
        # templates/

        Optional: add TemplateSpec YAML files for reusable script or function
        skeletons that an agent can adapt for `{import_name}`.

        Keep these generic. Do not add benchmark-specific or one-off tasks here.
        Delete this README when you add real templates, or if templates are not useful.

        ```yaml
        id: {import_name}.minimal_script
        task_tags: []
        description: "..."
        parameters: []
        code_template: |
          import {import_name}
        expected_artifacts: []
        ```
        """)


def _render_symbol_yaml(s: SymbolInfo, import_name: str) -> str:
    purpose = s.docstring.split("\n\n")[0] if s.docstring else ""
    mutates = ""
    if s.behavior_guess == "adata_mutation":
        mutates = "Mutates the first AnnData-like argument in place; verify exact writes manually."
    elif s.behavior_guess == "dataframe_mutation":
        mutates = "May mutate the first DataFrame-like argument; verify exact writes manually."

    data = {
        "id": f"{import_name}.{s.name}",
        "import_path": s.qual_name,
        "kind": "class" if s.is_class else "function",
        "signature": s.signature,
        "purpose": purpose,
        "description": purpose,
        "parameters": s.parameters,
        "mutates": mutates,
        "returns": s.return_annotation,
        "requires": [],
        "writes": [],
        "examples": [],
        "failure_fixes": [],
        "related": [],
    }
    header = (
        f"# Auto-generated stub for {s.qual_name}.\n"
        "# Review and fill: purpose, mutates, requires, "
        "writes, examples, failure_fixes, related.\n"
    )
    return header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


# --- pyproject patching --------------------------------------------------


def _find_pyproject(package_root: Path) -> Path | None:
    """Walk up from *package_root* to the filesystem root looking for pyproject.toml."""
    cur = package_root
    while True:
        cand = cur / "pyproject.toml"
        if cand.is_file():
            return cand
        if cur.parent == cur:
            return None
        cur = cur.parent


def _patch_pyproject(path: Path, import_name: str, contract_class: str) -> bool:
    """Additively add [tool.biobabel] and the biobabel.manifest entry-point.

    Preserves the user's existing TOML formatting and comments via tomlkit.
    Returns True if any modification was written.
    """
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    changed = False

    tool = doc.setdefault("tool", tomlkit.table())
    if "biobabel" not in tool:
        biobabel_table = tomlkit.table()
        biobabel_table.add("contract_class", contract_class)
        tool["biobabel"] = biobabel_table
        changed = True

    project = doc.get("project")
    if project is None:
        project = tomlkit.table()
        doc["project"] = project
    eps = project.setdefault("entry-points", tomlkit.table())
    manifest_group_key = "biobabel.manifest"
    if manifest_group_key not in eps:
        group = tomlkit.table()
        group.add(import_name, f"{import_name}._biobabel:get_manifest")
        eps[manifest_group_key] = group
        changed = True
    else:
        group = eps[manifest_group_key]
        if import_name not in group:
            group.add(import_name, f"{import_name}._biobabel:get_manifest")
            changed = True

    if changed:
        path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return changed


# --- TODO list -----------------------------------------------------------


def _build_todos(
    symbols: list[SymbolInfo], contract_class: str, has_pyproject: bool
) -> list[str]:
    todos: list[str] = []

    # Pick top 5 by parameter count as a rough proxy for "most important to document first"
    candidates = sorted(
        (s for s in symbols if not s.is_class), key=lambda s: -len(s.parameters)
    )[:5]
    if candidates:
        names = ", ".join(c.name for c in candidates)
        todos.append(
            f"Fill the top-{len(candidates)} symbols/*.yaml (purpose / mutates / requires / writes / examples): {names}"
        )

    todos.append("Replace TODO placeholders in package.yaml (repo, distribution, display_name)")
    if contract_class in ("analysis", "mixed"):
        todos.append("Add WorkflowContract YAML under workflows/ for canonical multi-step analyses, or delete workflows/README_TODO.md")
    todos.append("Add TemplateSpec YAML under templates/ only for reusable code skeletons, or delete templates/README_TODO.md")
    todos.append("Write skill.md (replace TODO sections)")

    if contract_class in ("grammar", "mixed"):
        todos.append(
            "Add at least one ConceptSpec under concepts/, one IdiomSpec under idioms/, "
            "and one AntiPatternSpec under anti_patterns/ (delete the README_TODO.md files)"
        )

    if not has_pyproject:
        todos.append(
            "pyproject.toml not found — manually add [tool.biobabel] and the "
            "[project.entry-points.\"biobabel.manifest\"] entry"
        )

    todos.append("Run: biobabel validate package --pkg <import_name> --strict")

    return todos
