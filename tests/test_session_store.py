"""SessionStore: the default-session abstraction added by the P2-2 trim.

``biobabel.create_session`` is gone from the MCP surface; the server-side
:meth:`SessionStore.get_or_create_default` is the lazy replacement. These
tests pin its invariants so the trim doesn't regress.
"""

from __future__ import annotations

from biobabel._runtime.session import SessionStore


def test_get_or_create_default_creates_lazily(tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    assert store.list_sessions() == []
    sess = store.get_or_create_default()
    assert sess.session_id in store.list_sessions()


def test_get_or_create_default_is_idempotent(tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    s1 = store.get_or_create_default()
    s2 = store.get_or_create_default()
    assert s1 is s2
    assert len(store.list_sessions()) == 1


def test_default_recreated_after_explicit_delete(tmp_path):
    """If the default gets deleted (e.g. shutdown / cleanup), the next
    call must re-create rather than raise — sessions are plumbing."""
    store = SessionStore(root=tmp_path / "sessions")
    s1 = store.get_or_create_default()
    store.delete(s1.session_id)
    s2 = store.get_or_create_default()
    assert s2 is not s1
    assert s2.session_id != s1.session_id


def test_iter_sessions_yields_id_session_pairs(tmp_path):
    store = SessionStore(root=tmp_path / "sessions")
    a = store.get_or_create_default()
    b = store.create()
    pairs = dict(store.iter_sessions())
    assert pairs[a.session_id] is a
    assert pairs[b.session_id] is b
