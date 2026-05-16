"""Group 6 — Runtime (8 tools)."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from biobabel._registry.builder import Registry
from biobabel._runtime.artifacts import ArtifactHandle
from biobabel._runtime.sandbox import run_code as _sandbox_run
from biobabel._runtime.session import AdataHandle, DfHandle, SessionStore
from biobabel.mcp.envelope import error, success


def create_session(sessions: SessionStore) -> dict[str, Any]:
    sess = sessions.create()
    return success(
        "biobabel.create_session",
        summary=f"created {sess.session_id}",
        outputs={"session_id": sess.session_id, "workspace": str(sess.workspace)},
    )


def list_handles(sessions: SessionStore, *, session_id: str) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return error(
            "biobabel.list_handles",
            error_code="session_not_found",
            message=f"no session '{session_id}'",
        )
    return success(
        "biobabel.list_handles",
        summary="ok",
        outputs={"handles": sess.list_handles()},
    )


def load_adata(sessions: SessionStore, *, session_id: str, path: str) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return error(
            "biobabel.load_adata",
            error_code="session_not_found",
            message=f"no session '{session_id}'",
        )
    src = Path(path)
    if not src.is_file():
        return error(
            "biobabel.load_adata",
            error_code="not_found",
            message=f"h5ad not found: {src}",
        )

    # Inspect via subprocess so that anndata import doesn't pollute biobabel proc.
    probe_code = f"""
import json, sys, anndata as ad
a = ad.read_h5ad({str(src)!r})
out = dict(
    shape=list(a.shape),
    obs_keys=list(a.obs.columns),
    var_keys=list(a.var.columns),
    obsm_keys=list(a.obsm.keys()),
    uns_keys=list(a.uns.keys()),
    layers=list(a.layers.keys()),
)
print('__BIOBABEL_ADATA__', json.dumps(out))
"""
    res = _sandbox_run(probe_code, sess.workspace)
    if not res.ok:
        return error(
            "biobabel.load_adata",
            error_code="probe_failed",
            message=res.stderr[-400:] or "h5ad probe failed",
        )
    payload: dict[str, Any] = {}
    for line in res.stdout.splitlines():
        if line.startswith("__BIOBABEL_ADATA__ "):
            payload = json.loads(line[len("__BIOBABEL_ADATA__ ") :])
            break
    adata_id = f"adata_{uuid.uuid4().hex[:12]}"
    handle = AdataHandle(
        adata_id=adata_id,
        path=src,
        shape=tuple(payload.get("shape", [])) or None,
        obs_keys=payload.get("obs_keys", []),
        obsm_keys=payload.get("obsm_keys", []),
        var_keys=payload.get("var_keys", []),
        uns_keys=payload.get("uns_keys", []),
        layers=payload.get("layers", []),
    )
    sess.add_adata(handle)
    return success(
        "biobabel.load_adata",
        summary=f"loaded {adata_id} (shape={handle.shape})",
        outputs={"adata_id": adata_id, "snapshot": payload},
    )


def load_dataframe(sessions: SessionStore, *, session_id: str, path: str) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return error("biobabel.load_dataframe", error_code="session_not_found", message=session_id)
    src = Path(path)
    if not src.is_file():
        return error("biobabel.load_dataframe", error_code="not_found", message=str(src))
    suffix = src.suffix.lower()
    reader = {"csv": "pd.read_csv", "tsv": "pd.read_csv", "parquet": "pd.read_parquet"}.get(
        suffix.lstrip(".")
    )
    if reader is None:
        return error("biobabel.load_dataframe", error_code="unsupported_format", message=suffix)
    sep_kw = ", sep='\\t'" if suffix == ".tsv" else ""
    probe = f"""
import json, pandas as pd
df = {reader}({str(src)!r}{sep_kw})
print('__BIOBABEL_DF__', json.dumps(dict(
    shape=list(df.shape),
    columns=list(df.columns),
    dtypes={{c: str(d) for c, d in df.dtypes.items()}},
)))
"""
    res = _sandbox_run(probe, sess.workspace)
    if not res.ok:
        return error(
            "biobabel.load_dataframe",
            error_code="probe_failed",
            message=res.stderr[-400:] or "probe failed",
        )
    payload: dict[str, Any] = {}
    for line in res.stdout.splitlines():
        if line.startswith("__BIOBABEL_DF__ "):
            payload = json.loads(line[len("__BIOBABEL_DF__ ") :])
            break
    df_id = f"df_{uuid.uuid4().hex[:12]}"
    handle = DfHandle(
        df_id=df_id,
        path=src,
        shape=tuple(payload.get("shape", [])) or None,
        columns=payload.get("columns", []),
        dtypes=payload.get("dtypes", {}),
    )
    sess.add_df(handle)
    return success(
        "biobabel.load_dataframe",
        summary=f"loaded {df_id} (shape={handle.shape})",
        outputs={"df_id": df_id, "snapshot": payload},
    )


def run_code(
    registry: Registry,
    sessions: SessionStore,
    *,
    session_id: str,
    code: str,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return error("biobabel.run_code", error_code="session_not_found", message=session_id)
    pre = {p for p in sess.workspace.rglob("*") if p.is_file()}
    extra_allow = list(registry.packages.keys())
    res = _sandbox_run(code, sess.workspace, timeout_s=timeout_s, extra_allow_imports=extra_allow)
    new_artifacts: list[dict[str, Any]] = []
    if res.ok:
        post = {p for p in sess.workspace.rglob("*") if p.is_file()}
        for path in sorted(post - pre):
            artifact_id = f"art_{uuid.uuid4().hex[:12]}"
            handle = ArtifactHandle.from_path(
                artifact_id=artifact_id,
                path=path,
                content_type=_guess_content_type(path),
                artifact_type=path.suffix.lstrip("."),
                source_tool="biobabel.run_code",
                source_code_hash=res.code_hash,
            )
            sess.add_artifact(handle)
            new_artifacts.append(
                {
                    "artifact_id": artifact_id,
                    "path": str(path),
                    "size_bytes": handle.size_bytes,
                    "content_type": handle.content_type,
                }
            )

    payload = {
        "ok": res.ok,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "duration_ms": round(res.duration_ms, 1),
        "return_code": res.return_code,
        "timed_out": res.timed_out,
        "new_artifacts": new_artifacts,
        "code_hash": res.code_hash,
    }
    if res.ok:
        return success(
            "biobabel.run_code",
            summary=f"ran in {res.duration_ms:.0f}ms, {len(new_artifacts)} artifact(s)",
            outputs=payload,
            state_updates={"new_artifacts": new_artifacts},
        )
    return error(
        "biobabel.run_code",
        error_code=res.error_code or "execution_failed",
        message=res.stderr[-400:] or "non-zero exit",
        details=payload,
    )


def run_recipe(
    registry: Registry,
    sessions: SessionStore,
    *,
    session_id: str,
    recipe_id: str,
    kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return error("biobabel.run_recipe", error_code="session_not_found", message=session_id)
    recipe_pkg, recipe = _find_recipe(registry, recipe_id)
    if recipe is None:
        return error(
            "biobabel.run_recipe",
            error_code="not_found",
            message=f"recipe '{recipe_id}' not registered",
        )
    import importlib
    try:
        mod = importlib.import_module(recipe_pkg)
    except ImportError as exc:
        return error("biobabel.run_recipe", error_code="import_failed", message=repr(exc))
    if mod.__file__ is None:
        return error("biobabel.run_recipe", error_code="bad_package", message="no __file__")
    biobabel_dir = Path(mod.__file__).parent / "_biobabel"
    recipe_path = (biobabel_dir / recipe.path).resolve()
    if not recipe_path.is_file():
        return error(
            "biobabel.run_recipe",
            error_code="recipe_file_missing",
            message=str(recipe_path),
        )
    code = recipe_path.read_text(encoding="utf-8")
    extra_allow = list(registry.packages.keys())
    if kwargs:
        prelude = "BIOBABEL_RECIPE_KWARGS = " + json.dumps(kwargs) + "\n"
        code = prelude + code
    res = _sandbox_run(code, sess.workspace, extra_allow_imports=extra_allow)
    return _wrap_run_result("biobabel.run_recipe", sess, res)


def inspect_object(sessions: SessionStore, *, session_id: str, adata_id: str, slot: str) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return error("biobabel.inspect_object", error_code="session_not_found", message=session_id)
    adata = sess.get_adata(adata_id)
    if adata is None:
        return error("biobabel.inspect_object", error_code="adata_not_found", message=adata_id)
    snapshot_map = {
        "obs_keys": adata.obs_keys,
        "obsm_keys": adata.obsm_keys,
        "var_keys": adata.var_keys,
        "uns_keys": adata.uns_keys,
        "layers": adata.layers,
        "shape": adata.shape,
    }
    if slot not in snapshot_map:
        return error("biobabel.inspect_object", error_code="bad_slot", message=slot)
    return success(
        "biobabel.inspect_object",
        summary=f"{adata_id}.{slot}",
        outputs={"slot": slot, "value": snapshot_map[slot]},
    )


def get_artifact(sessions: SessionStore, *, session_id: str, artifact_id: str) -> dict[str, Any]:
    sess = sessions.get(session_id)
    if sess is None:
        return error("biobabel.get_artifact", error_code="session_not_found", message=session_id)
    a = sess.get_artifact(artifact_id)
    if a is None:
        return error("biobabel.get_artifact", error_code="not_found", message=artifact_id)
    return success(
        "biobabel.get_artifact",
        summary=f"{a.artifact_id} ({a.size_bytes} bytes)",
        outputs={
            "artifact_id": a.artifact_id,
            "path": str(a.path),
            "content_type": a.content_type,
            "artifact_type": a.artifact_type,
            "size_bytes": a.size_bytes,
            "content_hash": a.content_hash,
            "source_tool": a.source_tool,
            "source_code_hash": a.source_code_hash,
            "package_versions": a.package_versions,
            "metadata": a.metadata,
        },
    )


# --- helpers --------------------------------------------------------------


def _wrap_run_result(tool_name: str, sess, res) -> dict[str, Any]:
    if res.ok:
        return success(
            tool_name,
            summary=f"ran in {res.duration_ms:.0f}ms",
            outputs={
                "stdout": res.stdout,
                "duration_ms": round(res.duration_ms, 1),
                "code_hash": res.code_hash,
            },
        )
    return error(
        tool_name,
        error_code=res.error_code or "execution_failed",
        message=res.stderr[-400:] or "non-zero exit",
        details={"stdout": res.stdout, "stderr": res.stderr, "code_hash": res.code_hash},
    )


def _find_recipe(registry: Registry, recipe_id: str):
    for d in registry.packages.values():
        for r in d.manifest.recipes:
            if r.id == recipe_id:
                return d.import_name, r
    return "", None


def _guess_content_type(path: Path) -> str:
    return {
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pdf": "application/pdf",
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".json": "application/json",
        ".h5ad": "application/x-hdf5",
        ".parquet": "application/x-parquet",
    }.get(path.suffix.lower(), "application/octet-stream")
