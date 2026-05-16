"""AST safety scan."""

from __future__ import annotations

from biobabel._runtime.policy import scan_code


def test_safe_code_passes():
    code = "import numpy as np\nx = np.arange(10)\nprint(x.sum())"
    res = scan_code(code)
    assert res.ok
    assert not res.violations


def test_subprocess_import_denied():
    res = scan_code("import subprocess\nsubprocess.run(['ls'])")
    assert not res.ok
    assert any("subprocess" in v.detail for v in res.violations)


def test_os_attribute_access_denied():
    res = scan_code("import os\nos.system('rm -rf /')")
    assert not res.ok


def test_eval_forbidden():
    res = scan_code("x = eval('1+1')")
    assert not res.ok
    assert any(v.kind == "forbidden_call" for v in res.violations)


def test_socket_denied():
    res = scan_code("import socket\nsocket.socket()")
    assert not res.ok


def test_syntax_error_caught():
    res = scan_code("def foo(:\n")
    assert not res.ok
    assert res.violations[0].kind == "syntax_error"
