"""Build SKILL.md per discovered package.

Each output SKILL.md is the upstream package's narrative `skill.md` with
biobabel-provided front-matter prepended:

```yaml
---
name: use-<import-name>
description: <one-line — taken from package manifest display_name>
generated_from_registry_commit: <sha256 of the manifest>
contract_class: <analysis|grammar|mixed>
package_version: <distribution_version>
biobabel_version: <biobabel.__version__>
---
```

The `generated_from_registry_commit` field lets CI assert the skills are
in sync with the contracts (final_plan §18.3 drift rule).

In addition, a top-level `biobabel-overview/SKILL.md` is always emitted —
hand-curated content explaining the 20 MCP tools and the two-class framework.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from biobabel import __version__ as BIOBABEL_VERSION
from biobabel._registry.builder import Registry
from biobabel._registry.sha import manifest_sha256


@dataclass
class SkillBuildResult:
    written: list[Path] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (pkg, reason)


def build_skills(registry: Registry, out_dir: Path) -> SkillBuildResult:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    result = SkillBuildResult()

    # 1. The handwritten overview skill — always emitted.
    overview_dir = out_dir / "biobabel-overview"
    overview_dir.mkdir(parents=True, exist_ok=True)
    overview = overview_dir / "SKILL.md"
    overview.write_text(_render_overview(registry), encoding="utf-8")
    result.written.append(overview)

    # 2. Per-package skills.
    for d in registry.list_packages():
        m = d.manifest
        skill_md_source = _read_package_skill_md(d)
        if skill_md_source is None:
            result.skipped.append((d.import_name, "no _biobabel/skill.md in package source"))
            continue

        sha = manifest_sha256(m)
        slug = d.import_name.replace("_", "-")
        skill_dir = out_dir / f"use-{slug}"
        skill_dir.mkdir(parents=True, exist_ok=True)
        rendered = _render_package_skill(
            import_name=d.import_name,
            distribution_version=d.distribution_version,
            contract_class=m.contract_class,
            display_name=m.display_name,
            manifest_sha=sha,
            body=skill_md_source,
        )
        skill_path = skill_dir / "SKILL.md"
        skill_path.write_text(rendered, encoding="utf-8")
        result.written.append(skill_path)

    return result


def _read_package_skill_md(d) -> str | None:  # type: ignore[no-untyped-def]
    """Locate `<pkg>/_biobabel/skill.md` for this discovered manifest."""
    import importlib.util
    spec = importlib.util.find_spec(d.import_name)
    if spec is None or spec.origin is None:
        return None
    skill_path = Path(spec.origin).parent / "_biobabel" / "skill.md"
    if not skill_path.is_file():
        return None
    raw = skill_path.read_text(encoding="utf-8")
    # Strip any pre-existing YAML front-matter — we'll write our own.
    return _strip_frontmatter(raw).strip()


_FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _strip_frontmatter(text: str) -> str:
    return _FRONT_MATTER.sub("", text, count=1)


def _render_package_skill(
    *,
    import_name: str,
    distribution_version: str,
    contract_class: str,
    display_name: str,
    manifest_sha: str,
    body: str,
) -> str:
    slug = import_name.replace("_", "-")
    description = _one_line(display_name or import_name)
    front = (
        f"---\n"
        f"name: use-{slug}\n"
        f"description: {description}\n"
        f"contract_class: {contract_class}\n"
        f"package_version: {distribution_version}\n"
        f"biobabel_version: {BIOBABEL_VERSION}\n"
        f"generated_from_registry_commit: {manifest_sha}\n"
        f"---\n\n"
    )
    return front + body + "\n"


def _render_overview(registry: Registry) -> str:
    pkg_count = len(registry.packages)
    by_class: dict[str, list[str]] = {"analysis": [], "grammar": [], "mixed": []}
    for d in registry.list_packages():
        by_class[d.manifest.contract_class].append(d.import_name)

    lines = [
        "---",
        "name: biobabel-overview",
        "description: 20 MCP tools for Bio-Babel — discover, plan, validate, and run registered Bio-Babel packages. Read this first when the user mentions an R bioinformatics package or a Bio-Babel name.",
        f"biobabel_version: {BIOBABEL_VERSION}",
        "---",
        "",
        "# biobabel",
        "",
        f"Bio-Babel's agent control plane currently surfaces **{pkg_count}** package(s):",
        "",
    ]
    for cls in ("analysis", "grammar", "mixed"):
        names = by_class[cls]
        if names:
            lines.append(f"- **Class {cls}**: {', '.join(sorted(names))}")
    if pkg_count == 0:
        lines.append("- *(no packages registered yet — run `biobabel index`)*")
    lines.extend([
        "",
        "## Decision tree",
        "",
        "Pick the route by what the user is doing:",
        "",
        "| User says                                                        | Reach for                                            |",
        "|------------------------------------------------------------------|------------------------------------------------------|",
        "| \"run pseudotime / trajectory / monocle3 / copykat / clustering\"  | `biobabel.list_packages` (read triggers/tags) → `biobabel.plan_workflow` (Class A) |",
        "| \"draw / plot / custom geom / grid / ggplot2 / pheatmap\"          | `biobabel.list_packages` (read triggers/tags) → `biobabel.describe_concept` + `list_idioms` (Class B) |",
        "| pastes R syntax (`library(`, `<-`, `%>%`)                        | look up the Python contract with `describe_symbol` / `describe_concept` / `list_idioms` |",
        "| \"add biobabel support to my package\"                             | use the maintainer CLI: `biobabel new contract --pkg <import_name>` |",
        "| review a Bio-Babel R-port PR                                     | inspect `_biobabel/` contracts and run the package tests directly |",
        "",
        "## Hard rules",
        "",
        "1. Never echo R syntax as Python. Look up the Python-side contract instead of translating line-by-line.",
        "2. For Class A packages, run `biobabel.check_prerequisites` before any step that requires upstream state.",
        "3. For Class B packages, run `biobabel.check_code` on any non-trivial snippet before showing it to the user — anti-pattern detection catches the cardinal footguns.",
        "4. `biobabel.run_code` runs in a guarded subprocess; it catches common agent mistakes but is not a security boundary.",
        "5. After runtime failures or confusing multi-step state, call `biobabel.list_traces()` to inspect recent runtime calls in the default session.",
        "",
        "## Discovering more",
        "",
        "- `biobabel.list_packages()` — registry snapshot",
        "- `biobabel.list_tools()` — full MCP tool list",
        "- `biobabel.list_idioms(package=X)` — Class B grammar patterns",
        "- `biobabel.health()` — discovery errors + session state",
        "- `biobabel.list_traces()` — recent runtime calls, handle refs, artifact refs, and code hashes",
        "",
    ])
    return "\n".join(lines)


def _one_line(text: str) -> str:
    return " ".join(text.split())[:160]
