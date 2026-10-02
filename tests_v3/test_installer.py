"""Exercise Windows launcher failures without creating/installing an environment."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows CMD launcher contract")
REPO = Path(__file__).resolve().parents[1]


def project_copy(tmp_path, *, with_app=True):
    project = tmp_path / "설치 검증 (새 폴더)"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(REPO / "INSTALL.cmd", project / "INSTALL.cmd")
    shutil.copy2(REPO / "scripts" / "install_environment.py", project / "scripts" / "install_environment.py")
    (project / "requirements.txt").write_text("", encoding="utf-8")
    if with_app:
        (project / "app.py").write_text("# installer fixture; never run\n", encoding="utf-8")
    return project


def environment(*, explicit_python=True, no_path=False):
    env = os.environ.copy()
    env.pop("AM_DFM_PYTHON", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    if explicit_python:
        env["AM_DFM_PYTHON"] = sys.executable
    if no_path:
        env["PATH"] = ""
    return env


def command(project, *args):
    # Supply the exact Windows command line: list2cmdline quoting is not CMD quoting.
    cmd = os.environ.get("COMSPEC", str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"))
    return f'"{cmd}" /d /s /c ""{project / "INSTALL.cmd"}" {" ".join(args)}"'


def invoke(project, *args, env=None):
    return subprocess.run(
        command(project, *args),
        cwd=project.parent,
        env=environment() if env is None else env,
        input="\n",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def test_diagnose_explicit_runtime_from_korean_space_parentheses_path(tmp_path):
    project = project_copy(tmp_path)
    result = invoke(project, "--diagnose", "--no-pause", env=environment(no_path=True))
    assert result.returncode == 0, result.stdout
    assert "diagnos" in result.stdout.lower(), result.stdout
    assert str(project).lower() in result.stdout.lower(), result.stdout
    assert not (project / ".venv").exists(), "Diagnosis must not create an environment"


def test_missing_project_file_preserves_error_and_log_without_install(tmp_path):
    project = project_copy(tmp_path, with_app=False)
    result = invoke(project, "--no-pause")
    assert result.returncode != 0, result.stdout
    assert "app.py" in result.stdout, result.stdout
    logs = list((project / "logs").glob("install-*.log"))
    assert logs, result.stdout
    assert any("app.py" in p.read_text(encoding="utf-8", errors="replace") for p in logs)
    assert not (project / ".venv").exists(), "Project validation must precede installation"


def test_default_failed_install_waits_for_user_then_returns_failure(tmp_path):
    project = project_copy(tmp_path, with_app=False)
    process = subprocess.Popen(
        command(project), cwd=project.parent, env=environment(),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        # Keeping stdin open reproduces Explorer's window: failure must reach pause.
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(timeout=3)
        output, _ = process.communicate(input=b"\r\n", timeout=30)
        assert process.returncode != 0, output.decode("utf-8", errors="replace")
        assert b"app.py" in output, output.decode("utf-8", errors="replace")
        assert not (project / ".venv").exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


def test_missing_runtime_exits_with_visible_error_without_install(tmp_path):
    project = project_copy(tmp_path)
    result = invoke(project, "--diagnose", "--no-pause", env=environment(explicit_python=False, no_path=True))
    assert result.returncode != 0, result.stdout
    assert "python" in result.stdout.lower(), result.stdout
    assert not (project / ".venv").exists()


def test_diagnose_preserves_existing_broken_environment(tmp_path):
    project = project_copy(tmp_path)
    scripts = project / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (scripts / "python.exe").write_bytes(b"invalid executable: preserve user environment")
    (scripts.parent / "pyvenv.cfg").write_text("home = C:\\missing-python\n", encoding="utf-8")
    (scripts.parent / "user-note.txt").write_text("do not delete this environment", encoding="utf-8")
    before = {p.relative_to(scripts.parent): p.read_bytes() for p in scripts.parent.rglob("*") if p.is_file()}
    result = invoke(project, "--diagnose", "--no-pause")
    after = {p.relative_to(scripts.parent): p.read_bytes() for p in scripts.parent.rglob("*") if p.is_file()}
    assert after == before, result.stdout
    assert "venv" in result.stdout.lower(), result.stdout
