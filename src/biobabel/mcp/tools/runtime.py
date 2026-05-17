"""Group 5 — Runtime (6 tools).

Surface trim landed alongside P2-3 streaming: ``create_session`` and
``list_handles`` were removed from the public MCP surface. The session
lifecycle is now server-side plumbing — the LLM never sees it.

Each runtime handler:

- Accepts ``session_id: str | None = None``. ``None`` resolves to the
  per-process default session (see ``SessionStore.get_or_create_default``).
  An explicit but unknown ``session_id`` is a loud ``session_not_found``
  error rather than a silent fallback.
- Returns ``session_id`` + ``active_handles`` in ``outputs`` on success,
  so the LLM always sees the current session shape without a separate
  ``list_handles`` round-trip.
- Accepts a ``progress: ProgressEmitter`` injected by the server when the
  client passed an MCP ``progressToken``. Only ``run_code`` and
  ``run_recipe`` actually emit chunks; the rest receive a noop emitter.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from biobabel._registry.builder import Registry
from biobabel._runtime.artifacts import ArtifactHandle
from biobabel._runtime.sandbox import StreamChunk
from biobabel._runtime.sandbox import run_code as _sandbox_run
from biobabel._runtime.session import AdataHandle, DfHandle, Session, SessionStore
from biobabel.mcp.envelope import error, success

# Server-injected, per-call. Streaming tools forward subprocess StreamChunks
# through this; non-streaming tools accept the parameter but never emit.
# ``dict[str, Any]`` is the payload shape the transport translates into an
# MCP ``notifications/progress`` event (with ``message`` carrying a
# JSON-encoded payload).
ProgressEmitter = Callable[[dict[str, Any]], None]


def _noop_progress(_payload: dict[str, Any]) -> None:
    pass


def _resolve_session(
    sessions: SessionStore, session_id: str | None, tool_name: str
) -> tuple[Session, dict[str, Any] | None]:
    """Return ``(session, None)`` on success, or ``(_, error_envelope)`` on miss.

    ``None`` session_id → lazy default. An explicit-but-unknown id is a
    loud error: callers that bother to pass a session_id deserve a clear
    "you asked for X, X does not exist" rather than silent re-routing.
    """
    if session_id is None:
        return sessions.get_or_create_default(), None
    sess = sessions.get(session_id)
    if sess is None:
        return None, error(  # type: ignore[return-value]
            tool_name, error_code="session_not_found",
            message=f"no session '{session_id}'",
        )
    return sess, None


def _augment_runtime_outputs(env: dict[str, Any], sess: Session) -> dict[str, Any]:
    """Stamp every successful runtime response with session_id + active_handles.

    Failure envelopes are returned unchanged; "you don't have a session"
    or "the recipe wasn't found" should not advertise current handles.
    """
    if env.get("ok") is True:
        outputs = env.setdefault("outputs", {})
        outputs.setdefault("session_id", sess.session_id)
        outputs.setdefault("active_handles", sess.list_handles())
    return env


# --- public runtime handlers ----------------------------------------------


def load_adata(
    sessions: SessionStore,
    progress: ProgressEmitter,
    *,
    path: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    sess, err = _resolve_session(sessions, session_id, "biobabel.load_adata")
    if err is not None:
        return err
    src = Path(path)
    if not src.is_file():
        return error(
            "biobabel.load_adata",
            error_code="not_found",
            message=f"h5ad not found: {src}",
        )

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
    return _augment_runtime_outputs(
        success(
            "biobabel.load_adata",
            summary=f"loaded {adata_id} (shape={handle.shape})",
            outputs={"adata_id": adata_id, "snapshot": payload},
        ),
        sess,
    )


def load_dataframe(
    sessions: SessionStore,
    progress: ProgressEmitter,
    *,
    path: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    sess, err = _resolve_session(sessions, session_id, "biobabel.load_dataframe")
    if err is not None:
        return err
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
    return _augment_runtime_outputs(
        success(
            "biobabel.load_dataframe",
            summary=f"loaded {df_id} (shape={handle.shape})",
            outputs={"df_id": df_id, "snapshot": payload},
        ),
        sess,
    )


def run_code(
    registry: Registry,
    sessions: SessionStore,
    progress: ProgressEmitter,
    *,
    code: str,
    session_id: str | None = None,
    timeout_s: int | None = None,
) -> dict[str, Any]:
    sess, err = _resolve_session(sessions, session_id, "biobabel.run_code")
    if err is not None:
        return err
    pre = {p for p in sess.workspace.rglob("*") if p.is_file()}
    extra_allow = list(registry.packages.keys())

    def _emit(chunk: StreamChunk) -> None:
        progress({"event": "stream", "stream": chunk.stream, "text": chunk.text})

    res = _sandbox_run(
        code,
        sess.workspace,
        timeout_s=timeout_s,
        extra_allow_imports=extra_allow,
        on_progress=_emit,
    )

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
        return _augment_runtime_outputs(
            success(
                "biobabel.run_code",
                summary=f"ran in {res.duration_ms:.0f}ms, {len(new_artifacts)} artifact(s)",
                outputs=payload,
                state_updates={"new_artifacts": new_artifacts},
            ),
            sess,
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
    progress: ProgressEmitter,
    *,
    recipe_id: str,
    session_id: str | None = None,
    kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sess, err = _resolve_session(sessions, session_id, "biobabel.run_recipe")
    if err is not None:
        return err
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
        # Producer package not installed in this env. Converted to a
        # structured envelope rather than letting it bubble to the
        # transport-level generic "exception" handler, so the LLM gets
        # the specific ``import_failed`` error_code it can act on.
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

    def _emit(chunk: StreamChunk) -> None:
        progress({"event": "stream", "stream": chunk.stream, "text": chunk.text})

    res = _sandbox_run(
        code, sess.workspace, extra_allow_imports=extra_allow, on_progress=_emit
    )
    return _wrap_run_result("biobabel.run_recipe", sess, res)


def inspect_object(
    sessions: SessionStore,
    progress: ProgressEmitter,
    *,
    adata_id: str,
    slot: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    sess, err = _resolve_session(sessions, session_id, "biobabel.inspect_object")
    if err is not None:
        return err
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
    return _augment_runtime_outputs(
        success(
            "biobabel.inspect_object",
            summary=f"{adata_id}.{slot}",
            outputs={"slot": slot, "value": snapshot_map[slot]},
        ),
        sess,
    )


def get_artifact(
    sessions: SessionStore,
    progress: ProgressEmitter,
    *,
    artifact_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    sess, err = _resolve_session(sessions, session_id, "biobabel.get_artifact")
    if err is not None:
        return err
    a = sess.get_artifact(artifact_id)
    if a is None:
        return error("biobabel.get_artifact", error_code="not_found", message=artifact_id)
    return _augment_runtime_outputs(
        success(
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
        ),
        sess,
    )


# --- helpers --------------------------------------------------------------


def _wrap_run_result(tool_name: str, sess: Session, res) -> dict[str, Any]:
    if res.ok:
        return _augment_runtime_outputs(
            success(
                tool_name,
                summary=f"ran in {res.duration_ms:.0f}ms",
                outputs={
                    "stdout": res.stdout,
                    "duration_ms": round(res.duration_ms, 1),
                    "code_hash": res.code_hash,
                },
            ),
            sess,
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
