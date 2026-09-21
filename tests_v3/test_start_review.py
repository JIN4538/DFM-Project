"""Windows launcher identity, duplicate-click behavior, and visible failures."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import start_review as launcher


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows launcher contract")
REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def app_root(tmp_path):
    root = tmp_path / "제조성 검토 (한글 폴더)"
    root.mkdir()
    (root / "app.py").write_text("# launcher fixture; never execute\n", encoding="utf-8")
    return root


def command_for(app, *, python=None):
    return [str(python or Path(sys.executable).resolve()), "-X", "utf8", "-m",
            "streamlit", "run", str(app), "--server.port", "8507"]


def verified_owner(monkeypatch, app_root, *, port=8507):
    arguments = command_for(app_root / "app.py")
    arguments[-1] = str(port)
    owner = {"ProcessId": 43210,
             "CommandLine": subprocess.list2cmdline(arguments)}
    monkeypatch.setattr(launcher, "listener_commands", lambda port: [owner])
    monkeypatch.setattr(launcher, "healthy", lambda url: True)
    return owner


def forbid_server_start(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("An existing/conflicting server must not be started or killed")
    monkeypatch.setattr(launcher.subprocess, "call", forbidden)
    monkeypatch.setattr(launcher.os, "kill", forbidden)


def test_native_windows_command_parser_preserves_korean_and_quoted_paths():
    arguments = [r"C:\검토 (새 폴더)\런타임\python.exe", "-X", "utf8", "-m",
                 "streamlit", "run", r"C:\제조성 & 설계 (검토)\app.py",
                 "--server.port", "8507"]
    assert launcher.windows_arguments(subprocess.list2cmdline(arguments)) == arguments


@pytest.mark.parametrize("utf8_option", [True, False])
def test_identity_accepts_exact_absolute_app_and_windows_case(app_root, utf8_option):
    arguments = command_for(app_root / "app.py")
    if not utf8_option:
        arguments[1:3] = []
    arguments[0] = arguments[0].upper()
    arguments[arguments.index("run") + 1] = str(app_root / "app.py").upper()
    assert launcher.is_this_app(arguments, app_root / "app.py", Path(sys.executable))


@pytest.mark.parametrize("change", ["relative", "other_folder", "other_module", "other_python"])
def test_identity_rejects_unproven_or_different_process(app_root, change):
    arguments = command_for(app_root / "app.py")
    if change == "relative":
        arguments[6] = "app.py"
    elif change == "other_folder":
        arguments[6] = str(app_root.parent / "different" / "app.py")
    elif change == "other_module":
        arguments[4] = "http.server"
    else:
        arguments[0] = str(app_root.parent / "other-runtime" / "python.exe")
    assert not launcher.is_this_app(arguments, app_root / "app.py", Path(sys.executable))


@pytest.mark.parametrize("case, expected", [("known_base", True), ("other_python", False),
                                           ("relative_app", False)])
def test_venv_base_interpreter_exception_still_requires_known_runtime_and_absolute_app(app_root, case, expected):
    base_python = app_root.parent / "known-python" / "python.exe"
    arguments = command_for(app_root / "app.py", python=base_python)
    if case == "other_python":
        arguments[0] = str(app_root.parent / "unrelated-python" / "python.exe")
    elif case == "relative_app":
        arguments[6] = "app.py"
    assert launcher.is_this_app(arguments, app_root / "app.py", Path(sys.executable), base_python) is expected


def test_reuse_accepts_windows_redirector_base_interpreter(monkeypatch, app_root):
    owner = verified_owner(monkeypatch, app_root)
    base_python = app_root.parent / "known-base-python" / "python.exe"
    monkeypatch.setattr(launcher.sys, "_base_executable", str(base_python))
    owner["CommandLine"] = subprocess.list2cmdline(command_for(app_root / "app.py", python=base_python))
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    forbid_server_start(monkeypatch)
    assert launcher.main(["--no-browser"], root=app_root) == 0


def test_healthy_duplicate_opens_existing_app_without_starting_server(monkeypatch, app_root):
    verified_owner(monkeypatch, app_root)
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    opened = []
    monkeypatch.setattr(launcher.webbrowser, "open", lambda url: opened.append(url) or True)
    forbid_server_start(monkeypatch)
    assert launcher.main([], root=app_root) == 0
    assert opened == ["http://127.0.0.1:8507/"]


@pytest.mark.parametrize("browser_failure", ["false", "exception"])
def test_browser_failure_keeps_healthy_server_success(monkeypatch, app_root, capsys, browser_failure):
    verified_owner(monkeypatch, app_root)
    monkeypatch.setattr(launcher, "port_available", lambda port: False)

    def open_browser(url):
        if browser_failure == "exception":
            raise OSError("No browser association")
        return False

    monkeypatch.setattr(launcher.webbrowser, "open", open_browser)
    forbid_server_start(monkeypatch)
    assert launcher.main([], root=app_root) == 0
    assert "Open this address in your browser: http://127.0.0.1:8507/" in capsys.readouterr().out


@pytest.mark.parametrize("owner_kind", ["other_app", "relative_app", "unavailable"])
def test_occupied_port_does_not_reuse_unverified_health_or_start_or_kill(
    monkeypatch, app_root, capsys, owner_kind
):
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    owner = verified_owner(monkeypatch, app_root)
    if owner_kind == "other_app":
        owner["CommandLine"] = subprocess.list2cmdline(command_for(app_root.parent / "other" / "app.py"))
    elif owner_kind == "relative_app":
        owner["CommandLine"] = subprocess.list2cmdline(command_for("app.py"))
    else:
        def denied(port):
            raise OSError("Process query denied")
        monkeypatch.setattr(launcher, "listener_commands", denied)
    forbid_server_start(monkeypatch)
    assert launcher.main(["--no-browser"], root=app_root) == 1
    output = capsys.readouterr().out
    assert "could not be confirmed" in output
    assert "START_REVIEW.cmd --port 8508" in output


def test_unhealthy_matching_process_is_not_reported_as_running(monkeypatch, app_root, capsys):
    verified_owner(monkeypatch, app_root)
    monkeypatch.setattr(launcher, "port_available", lambda port: False)
    monkeypatch.setattr(launcher, "healthy", lambda url: False)
    monkeypatch.setattr(launcher.time, "sleep", lambda seconds: None)
    forbid_server_start(monkeypatch)
    assert launcher.main(["--no-browser"], root=app_root) == 1
    assert "is already running" not in capsys.readouterr().out


def test_double_click_race_recovers_after_child_failure(monkeypatch, app_root):
    monkeypatch.setattr(launcher, "port_available", lambda port: True)
    verified_owner(monkeypatch, app_root, port=8512)
    started = []

    def competing_start(command, *, cwd):
        started.append((command, cwd))
        return 1  # Another launch acquired the port between probe and bind.

    monkeypatch.setattr(launcher.subprocess, "call", competing_start)
    assert launcher.main(["--port", "8512", "--no-browser"], root=app_root) == 0
    assert len(started) == 1
    command, cwd = started[0]
    assert Path(command[6]).is_absolute()
    assert command[6] == str(app_root / "app.py")
    assert cwd == app_root
    assert command[-6:] == ["--server.address", "127.0.0.1", "--server.port", "8512",
                            "--server.headless", "true"]


def test_child_failure_without_verified_server_preserves_exit_code(monkeypatch, app_root):
    monkeypatch.setattr(launcher, "port_available", lambda port: True)
    monkeypatch.setattr(launcher.subprocess, "call", lambda command, **kwargs: 7)
    monkeypatch.setattr(launcher, "listener_commands", lambda port: [])
    assert launcher.main(["--no-browser"], root=app_root) == 7


def test_missing_app_fails_before_port_probe_or_server_start(monkeypatch, tmp_path, capsys):
    def forbidden(port):
        pytest.fail("Missing app must fail before inspecting the network")
    monkeypatch.setattr(launcher, "port_available", forbidden)
    forbid_server_start(monkeypatch)
    assert launcher.main([], root=tmp_path) == 1
    assert "Missing app file:" in capsys.readouterr().out


def cmd_command(project, *args):
    comspec = os.environ.get("COMSPEC", str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"))
    return f'"{comspec}" /d /s /c ""{project / "START_REVIEW.cmd"}" {" ".join(args)}"'


def test_actual_cmd_missing_environment_waits_for_key_then_fails(app_root):
    shutil.copy2(REPO / "START_REVIEW.cmd", app_root / "START_REVIEW.cmd")
    process = subprocess.Popen(cmd_command(app_root), cwd=app_root.parent,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=2)
        output, _ = process.communicate(input=b"\r\n", timeout=10)
        assert process.returncode == 1, output
        assert b"Run INSTALL.cmd first." in output
        assert not (app_root / ".venv").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_actual_cmd_no_pause_option_preserves_missing_environment_failure(app_root):
    shutil.copy2(REPO / "START_REVIEW.cmd", app_root / "START_REVIEW.cmd")
    result = subprocess.run(cmd_command(app_root, "--no-pause"), cwd=app_root.parent,
                            capture_output=True, timeout=10)
    assert result.returncode == 1, result.stdout
    assert b"Run INSTALL.cmd first." in result.stdout
