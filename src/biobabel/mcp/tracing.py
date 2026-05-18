"""Lightweight per-session traces for runtime MCP calls."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from biobabel._runtime.session import Session, SessionStore
from biobabel._runtime.trace import TraceRecord

_HANDLE_KEYS = {"adata_id", "df_id", "plot_id", "artifact_id"}


def record_runtime_trace(
    sessions: SessionStore,
    tool_name: str,
    *,
    kwargs: dict[str, Any],
    envelope: dict[str, Any] | None,
    started_at: datetime,
    duration_ms: float,
    exception: Exception | None = None,
) -> None:
    """Record a runtime call against the actual session it used.

    Trace is deliberately narrow: runtime/session tools only, no raw code,
    no full argument payloads, and no process-level all-tool audit log.
    """
    sess = _session_for_runtime_trace(sessions, kwargs, envelope)
    if sess is None:
        return

    ok = envelope.get("ok") is True if envelope is not None else False
    error_code = ""
    if exception is not None:
        error_code = type(exception).__name__
    elif envelope is not None and not ok:
        error_code = str(envelope.get("error_code", ""))

    sess.record_trace(
        TraceRecord(
            tool_name=tool_name,
            started_at=started_at,
            duration_ms=round(duration_ms, 1),
            ok=ok,
            error_code=error_code,
            handle_refs_in=_handle_refs_in(kwargs),
            handle_refs_out=_handle_refs_out(tool_name, envelope),
            args_summary=_runtime_args_summary(tool_name, kwargs, envelope),
        )
    )


def _session_for_runtime_trace(
    sessions: SessionStore,
    kwargs: dict[str, Any],
    envelope: dict[str, Any] | None,
) -> Session | None:
    explicit_session_id = kwargs.get("session_id")
    if explicit_session_id is not None:
        return sessions.get(str(explicit_session_id))

    sid = _session_id_from_envelope(envelope)
    if sid is not None:
        sess = sessions.get(sid)
        if sess is not None:
            return sess
    return sessions.get_default()


def _session_id_from_envelope(envelope: dict[str, Any] | None) -> str | None:
    if envelope is None:
        return None
    outputs = envelope.get("outputs")
    if isinstance(outputs, dict) and isinstance(outputs.get("session_id"), str):
        return outputs["session_id"]
    details = envelope.get("details")
    if isinstance(details, dict) and isinstance(details.get("session_id"), str):
        return details["session_id"]
    return None


def _handle_refs_in(kwargs: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    _collect_named_handle_refs(kwargs, refs)
    return _dedupe(refs)


def _handle_refs_out(tool_name: str, envelope: dict[str, Any] | None) -> list[str]:
    if envelope is None or envelope.get("ok") is not True:
        return []
    outputs = envelope.get("outputs")
    if not isinstance(outputs, dict):
        return []
    refs: list[str] = []
    if tool_name == "biobabel.load_adata":
        _append_string_ref(outputs.get("adata_id"), refs)
    elif tool_name == "biobabel.load_dataframe":
        _append_string_ref(outputs.get("df_id"), refs)
    elif tool_name == "biobabel.run_code":
        for artifact in outputs.get("new_artifacts", []):
            if isinstance(artifact, dict):
                _append_string_ref(artifact.get("artifact_id"), refs)
    return _dedupe(refs)


def _runtime_args_summary(
    tool_name: str,
    kwargs: dict[str, Any],
    envelope: dict[str, Any] | None,
) -> dict[str, object]:
    summary: dict[str, object] = {}
    if tool_name in {"biobabel.load_adata", "biobabel.load_dataframe"}:
        path = kwargs.get("path")
        if isinstance(path, str):
            summary.update(_path_summary(path))
    elif tool_name == "biobabel.run_code":
        code = kwargs.get("code")
        if isinstance(code, str):
            summary["code_hash"] = hashlib.sha256(code.encode("utf-8")).hexdigest()
        if kwargs.get("timeout_s") is not None:
            summary["timeout_s"] = kwargs["timeout_s"]
    elif tool_name == "biobabel.run_recipe":
        if kwargs.get("recipe_id") is not None:
            summary["recipe_id"] = str(kwargs["recipe_id"])
        # run_recipe's code is the recipe file, not an agent argument; the
        # sandbox publishes its hash via the envelope payload.
        recipe_hash = _code_hash_from_envelope(envelope)
        if recipe_hash is not None:
            summary["code_hash"] = recipe_hash
    elif tool_name == "biobabel.inspect_object":
        # adata_id is already in handle_refs_in; only `slot` carries
        # information the handle ref doesn't.
        if kwargs.get("slot") is not None:
            summary["slot"] = str(kwargs["slot"])
    # biobabel.get_artifact: artifact_id is fully covered by handle_refs_in,
    # so no args_summary fields are needed.

    result = _runtime_result_summary(envelope)
    if result:
        summary["result"] = result
    return summary


def _runtime_result_summary(envelope: dict[str, Any] | None) -> dict[str, object]:
    if envelope is None:
        return {}
    payload = envelope.get("outputs") if envelope.get("ok") is True else envelope.get("details")
    if not isinstance(payload, dict):
        return {}

    result: dict[str, object] = {}
    for stream_name in ("stdout", "stderr"):
        stream = payload.get(stream_name)
        if isinstance(stream, str):
            result[f"{stream_name}_len"] = len(stream)
    if "timed_out" in payload:
        result["timed_out"] = payload["timed_out"]
    if isinstance(payload.get("duration_ms"), int | float):
        result["execution_duration_ms"] = payload["duration_ms"]
    return result


def _code_hash_from_envelope(envelope: dict[str, Any] | None) -> str | None:
    if envelope is None:
        return None
    payload = envelope.get("outputs") if envelope.get("ok") is True else envelope.get("details")
    if isinstance(payload, dict) and isinstance(payload.get("code_hash"), str):
        return payload["code_hash"]
    return None


def _path_summary(path: str) -> dict[str, object]:
    parsed = Path(path)
    return {
        "path_name": parsed.name,
        "path_suffix": parsed.suffix.lower(),
    }


def _collect_named_handle_refs(value: Any, refs: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _HANDLE_KEYS:
                _append_string_ref(child, refs)
            elif key != "code":
                _collect_named_handle_refs(child, refs)
    elif isinstance(value, list | tuple):
        for child in value:
            _collect_named_handle_refs(child, refs)


def _append_string_ref(value: Any, refs: list[str]) -> None:
    if isinstance(value, str):
        refs.append(value)


def _dedupe(refs: list[str]) -> list[str]:
    return list(dict.fromkeys(refs))
