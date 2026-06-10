"""biobabel CLI entry point.

Subcommands:
  index           — discover and index installed Bio-Babel packages
  validate        — validate a package's _biobabel/ contract
  doctor          — show registry + system health
  mcp             — launch the MCP stdio server
  new contract    — retrofit an existing installed Python package with a _biobabel/
  build-skills    — generate SKILL.md per registered package
  install         — write IDE config for Claude Code / Cursor / Continue / OpenAI
  uninstall       — remove biobabel from a previously-installed IDE config
  export-schema   — emit the manifest.v1 JSON Schema
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from biobabel import SCHEMA_VERSION
from biobabel._contracts.validator import validate_package_dir
from biobabel._registry.builder import build_registry
from biobabel._retrofit.retrofit import retrofit_package
from biobabel.manifest_api import PackageManifest

console = Console()


@click.group(help="biobabel — read-only contract layer for Bio-Babel.")
@click.version_option()
def main_cli() -> None:
    pass


@main_cli.command("index")
def cmd_index() -> None:
    reg = build_registry()
    table = Table(title=f"Discovered packages ({len(reg.packages)})")
    table.add_column("import_name")
    table.add_column("distribution")
    table.add_column("version")
    table.add_column("class")
    table.add_column("maturity")
    for d in reg.list_packages():
        table.add_row(
            d.import_name,
            d.distribution,
            d.distribution_version,
            d.manifest.contract_class,
            d.manifest.maturity,
        )
    console.print(table)
    if reg.errors:
        console.print(f"[yellow]{len(reg.errors)} discovery error(s):[/yellow]")
        for err in reg.errors:
            console.print(f"  - {err.name} ({err.distribution}): {err.error}")


@main_cli.command("doctor")
@click.option("--strict/--no-strict", default=False,
              help="Exit non-zero on any discovery error (default: warn only).")
def cmd_doctor(strict: bool) -> None:
    reg = build_registry()
    console.print(f"[bold]Packages registered:[/bold] {len(reg.packages)}")
    console.print(f"[bold]Discovery errors:[/bold] {len(reg.errors)}")
    for err in reg.errors:
        console.print(f"  ! {err.name} ({err.distribution}): {err.error}")

    exit_code = 1 if (strict and reg.errors) else 0
    raise SystemExit(exit_code)


@main_cli.group("validate")
def cmd_validate() -> None:
    """Validators (package contract / registry)."""


@cmd_validate.command("package")
@click.option("--pkg", "import_name", required=False,
              help="Import name; auto-resolve _biobabel/ directory via the installed package.")
@click.option("--dir", "biobabel_dir", type=click.Path(exists=True, file_okay=False),
              required=False, help="Path to a _biobabel/ directory.")
@click.option("--strict/--no-strict", default=True, help="Fail on warnings too.")
def cmd_validate_package(import_name: str | None, biobabel_dir: str | None, strict: bool) -> None:
    if biobabel_dir is None:
        if not import_name:
            click.echo("ERROR: pass --pkg <import_name> or --dir <path>", err=True)
            raise SystemExit(2)
        # find_spec locates the source tree WITHOUT executing the package —
        # works even for packages whose imports fail in this env.
        import importlib.util
        try:
            spec = importlib.util.find_spec(import_name)
        except (ImportError, ValueError) as exc:
            click.echo(f"ERROR: cannot find {import_name!r}: {exc}", err=True)
            raise SystemExit(2) from exc
        if spec is None or spec.origin is None:
            click.echo(
                f"ERROR: {import_name!r} has no locatable __init__.py "
                "(not installed, or namespace package).",
                err=True,
            )
            raise SystemExit(2)
        biobabel_dir = str(Path(spec.origin).parent / "_biobabel")

    report = validate_package_dir(Path(biobabel_dir))
    if report.ok and not report.warnings():
        console.print(f"[green]OK[/green] — {biobabel_dir}")
        return
    for issue in report.issues:
        style = {"error": "red", "warning": "yellow", "info": "blue"}.get(issue.severity, "")
        console.print(f"[{style}]{issue.severity.upper():7s}[/{style}] {issue.code}: {issue.message}")
        if issue.path:
            console.print(f"           → {issue.path}")
    if not report.ok:
        raise SystemExit(1)
    if strict and report.warnings():
        raise SystemExit(1)


@main_cli.command("export-schema")
@click.option("--out", "out_path", type=click.Path(), default="-",
              help="Output path or '-' for stdout.")
def cmd_export_schema(out_path: str) -> None:
    schema = PackageManifest.model_json_schema()
    schema["$id"] = f"https://bio-babel.github.io/biobabel/schemas/manifest.v{SCHEMA_VERSION}.json"
    payload = json.dumps(schema, indent=2, ensure_ascii=False)
    if out_path == "-":
        click.echo(payload)
    else:
        Path(out_path).write_text(payload + "\n", encoding="utf-8")
        console.print(f"[green]Wrote {out_path}[/green]")


@main_cli.command("mcp")
def cmd_mcp() -> None:
    """Launch the MCP stdio server (foreground)."""
    from biobabel.mcp.__main__ import main
    raise SystemExit(main())


@main_cli.group("new")
def cmd_new() -> None:
    """Create a new biobabel artefact for an existing target."""


@cmd_new.command("contract")
@click.option("--pkg", "import_name", required=True,
              help="Import name of an already pip-installed Python package.")
@click.option("--class", "contract_class",
              type=click.Choice(["analysis", "grammar", "mixed"]),
              default=None,
              help="contract_class; if omitted, biobabel will guess from package shape.")
@click.option("--r-package", "r_package", default=None,
              help="If this is a port of an R package, record the R package name.")
@click.option("--force/--no-force", default=False,
              help="Overwrite existing _biobabel/ (dangerous).")
@click.option("--dry-run/--no-dry-run", default=False,
              help="Show what would be done without writing files.")
def cmd_new_contract(
    import_name: str,
    contract_class: str | None,
    r_package: str | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Retrofit an already-installed Python package with a _biobabel/ contract."""
    result = retrofit_package(
        import_name=import_name,
        contract_class=contract_class,
        r_package=r_package,
        force=force,
        dry_run=dry_run,
    )
    if not result.ok:
        click.echo(f"ERROR: {result.error}", err=True)
        raise SystemExit(2)
    if dry_run:
        console.print(f"[yellow]DRY RUN — would write {len(result.written_files)} file(s):[/yellow]")
    else:
        console.print(f"[green]Generated {len(result.written_files)} file(s):[/green]")
    for p in result.written_files:
        console.print(f"  + {p}")
    if result.pyproject_patched:
        console.print(f"[green]Patched pyproject.toml at {result.pyproject_path}[/green]")
    console.print()
    console.print("[bold]Next steps:[/bold]")
    for i, todo in enumerate(result.todos, 1):
        console.print(f"  {i}. {todo}")


@main_cli.command("build-skills")
@click.option("--out", "out_dir", type=click.Path(), required=True,
              help="Output directory; one subdirectory per skill.")
def cmd_build_skills(out_dir: str) -> None:
    """Generate SKILL.md files from registered packages' _biobabel/skill.md."""
    from biobabel._exporters.skills import build_skills
    reg = build_registry()
    result = build_skills(reg, Path(out_dir))
    for p in result.written:
        console.print(f"[green]+[/green] {p}")
    for pkg, reason in result.skipped:
        console.print(f"[yellow]~ skipped {pkg}:[/yellow] {reason}")


@main_cli.command("install")
@click.option("--target",
              type=click.Choice(["claude_code", "cursor", "continue", "codex", "openai", "all"]),
              required=True)
@click.option("--workspace", type=click.Path(), default=".",
              help="Workspace path for per-project files (cursor rules, etc.)")
def cmd_install(target: str, workspace: str) -> None:
    from biobabel._exporters.installer import install
    written = install(target, Path(workspace))
    for p in written:
        console.print(f"[green]+[/green] {p}")


@main_cli.command("uninstall")
@click.option("--target",
              type=click.Choice(["claude_code", "cursor", "continue", "codex", "openai", "all"]),
              required=True)
@click.option("--workspace", type=click.Path(), default=".",
              help="Workspace path for per-project files (cursor rules, openai files).")
@click.option("--dry-run/--no-dry-run", default=False,
              help="Show what would be removed without modifying files.")
@click.option("--force/--no-force", default=False,
              help="Remove workspace artefacts even if their content has been modified.")
def cmd_uninstall(target: str, workspace: str, dry_run: bool, force: bool) -> None:
    """Remove the biobabel entry from the chosen IDE's MCP config.

    Symmetric to ``biobabel install``. Workspace artefacts (cursor rule,
    openai tools/prompt) are preserved if they have been modified relative
    to what install would write today; pass --force to remove them anyway.
    """
    from biobabel._exporters.installer import uninstall
    report = uninstall(target, Path(workspace), dry_run=dry_run, force=force)
    for line in report.actions:
        if line.startswith("DRY RUN"):
            console.print(f"[yellow]{line}[/yellow]")
        elif line.startswith("+"):
            console.print(f"[green]{line}[/green]")
        elif line.startswith("~"):
            console.print(f"[yellow]{line}[/yellow]")
        else:
            console.print(f"[dim]{line}[/dim]")
    if not report.actions:
        console.print("[dim](no actions)[/dim]")


def main(argv: list[str] | None = None) -> int:
    try:
        main_cli(args=argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
