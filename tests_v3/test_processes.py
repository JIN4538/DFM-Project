import os
import subprocess
import sys
import time

import pytest

from amdfm.processes import run_bounded
from amdfm import processes


def test_worker_output_and_exit_status(tmp_path):
    result=run_bounded([sys.executable,"-c","import sys; print('ready'); sys.exit(7)"],cwd=tmp_path,timeout=10)
    assert result.returncode==7
    assert result.stdout.strip()==b'ready'


def test_timeout_stops_child_before_it_can_write(tmp_path):
    marker=tmp_path/'orphan.txt'
    started=tmp_path/'started.txt'
    child="import time; from pathlib import Path; time.sleep(3); Path("+repr(str(marker))+").write_text('orphan')"
    worker=("import subprocess,sys,time; from pathlib import Path; "
            "subprocess.Popen([sys.executable,'-c',"+repr(child)+"]); "
            "Path("+repr(str(started))+").write_text('ready'); time.sleep(30)")
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable,'-c',worker],cwd=tmp_path,timeout=1.5)
    assert started.exists(), 'The child must actually be launched to exercise cleanup.'
    time.sleep(3)
    assert not marker.exists()


@pytest.mark.parametrize("redirect_child", [False, True])
def test_timeout_owns_child_after_direct_parent_has_exited(tmp_path, redirect_child):
    if os.name != "nt" and redirect_child:
        pytest.skip("Job active-process accounting is specific to Windows; Unix retains killpg on timeout.")
    marker = tmp_path / "late-child.txt"
    started = tmp_path / "parent-exited.txt"
    child = ("import time; from pathlib import Path; time.sleep(2); Path(" +
             repr(str(marker)) + ").write_text('must not run')")
    redirects = ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL" if redirect_child else ""
    worker = ("import subprocess,sys; from pathlib import Path; "
              "subprocess.Popen([sys.executable,'-c'," + repr(child) + "]" + redirects + "); "
              "Path(" + repr(str(started)) + ").write_text('parent exits now')")
    before = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, "-c", worker], cwd=tmp_path, timeout=.6)
    assert started.exists()
    assert time.monotonic() - before < 1.8
    time.sleep(2)
    assert not marker.exists()


def test_binary_output_larger_than_pipe_capacity_is_preserved(tmp_path):
    worker = "import sys; sys.stdout.buffer.write(b'\\x00\\xff' * 200000); sys.stderr.buffer.write(b'error' * 30000); sys.exit(9)"
    result = run_bounded([sys.executable, "-c", worker], cwd=tmp_path, timeout=10)
    assert result.returncode == 9
    assert result.stdout == b"\x00\xff" * 200000
    assert result.stderr == b"error" * 30000


def test_parent_exit_waits_for_successful_child_output_and_preserves_parent_code(tmp_path):
    child = "import sys,time; time.sleep(.1); print('child output'); sys.stderr.write('child error')"
    worker = "import subprocess,sys; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); sys.exit(7)"
    result = run_bounded([sys.executable, "-c", worker], cwd=tmp_path, timeout=5)
    assert result.returncode == 7
    assert result.stdout.strip() == b"child output"
    assert result.stderr == b"child error"


def test_timeout_preserves_already_flushed_output(tmp_path):
    worker = "import sys,time; print('before timeout',flush=True); sys.stderr.write('error'); sys.stderr.flush(); time.sleep(10)"
    with pytest.raises(subprocess.TimeoutExpired) as captured:
        run_bounded([sys.executable, "-c", worker], cwd=tmp_path, timeout=.4)
    assert captured.value.output.strip() == b"before timeout"
    assert captured.value.stderr == b"error"


def test_timing_out_one_job_does_not_stop_another_owned_control_process(tmp_path):
    marker = tmp_path / "unrelated-control.txt"
    command = "import time; from pathlib import Path; time.sleep(.5); Path(" + repr(str(marker)) + ").write_text('alive')"
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    control = subprocess.Popen([sys.executable, "-c", command], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, **flags)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_bounded([sys.executable, "-c", "import time; time.sleep(10)"], cwd=tmp_path, timeout=.1)
        assert control.wait(timeout=5) == 0
        assert marker.read_text() == "alive"
    finally:
        if control.poll() is None:
            control.kill()
            control.wait(timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended startup contract")
@pytest.mark.parametrize("failure_stage", ["assign", "resume"])
def test_setup_failure_never_runs_unowned_worker(tmp_path, monkeypatch, failure_stage):
    marker = tmp_path / "must-never-execute.txt"
    def fail(self, handle):
        time.sleep(.1)
        assert not marker.exists(), "The primary thread must still be suspended."
        raise OSError("injected " + failure_stage + " failure")
    monkeypatch.setattr(processes._WindowsJob, failure_stage, fail)
    worker = "from pathlib import Path; Path(" + repr(str(marker)) + ").write_text('unsafe')"
    before = time.monotonic()
    with pytest.raises(OSError, match="injected"):
        run_bounded([sys.executable, "-c", worker], cwd=tmp_path, timeout=10)
    assert time.monotonic() - before < 2
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows job kill-on-close fallback")
def test_termination_error_still_closes_job_and_stops_children(tmp_path, monkeypatch):
    marker = tmp_path / "kill-on-close.txt"
    def fail(self):
        raise OSError("injected TerminateJobObject failure")
    monkeypatch.setattr(processes._WindowsJob, "terminate", fail)
    child = "import time; from pathlib import Path; time.sleep(1); Path(" + repr(str(marker)) + ").write_text('unsafe')"
    worker = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child) + "]); time.sleep(10)"
    before = time.monotonic()
    with pytest.raises(OSError, match="정리 실패"):
        run_bounded([sys.executable, "-c", worker], cwd=tmp_path, timeout=.3)
    assert time.monotonic() - before < 1.5
    time.sleep(1)
    assert not marker.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle error reporting")
def test_close_error_is_not_reported_as_a_successful_measurement(tmp_path, monkeypatch):
    close = processes._WindowsJob.close
    def close_then_report_error(self):
        close(self)
        raise OSError("injected close failure after cleanup")
    monkeypatch.setattr(processes._WindowsJob, "close", close_then_report_error)
    with pytest.raises(OSError, match="정리 실패"):
        run_bounded([sys.executable, "-c", "print('complete')"], cwd=tmp_path, timeout=5)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_unbounded_or_invalid_timeouts_are_rejected(tmp_path, timeout):
    with pytest.raises(ValueError):
        run_bounded([sys.executable, "-c", "print('not run')"], cwd=tmp_path, timeout=timeout)


def test_missing_executable_fails_without_hanging(tmp_path):
    with pytest.raises(OSError):
        run_bounded([str(tmp_path / "no-such-executable.exe")], cwd=tmp_path, timeout=5)


@pytest.mark.skipif(os.name != "nt", reason="Windows owned handle accounting")
def test_repeated_workers_do_not_leak_handles(tmp_path):
    import ctypes as ct
    from ctypes import wintypes as wt
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wt.HANDLE
    kernel.GetProcessHandleCount.argtypes = [wt.HANDLE, ct.POINTER(wt.DWORD)]
    kernel.GetProcessHandleCount.restype = wt.BOOL
    def count():
        value = wt.DWORD()
        assert kernel.GetProcessHandleCount(kernel.GetCurrentProcess(), ct.byref(value))
        return value.value
    run_bounded([sys.executable, "-c", "pass"], cwd=tmp_path, timeout=5)
    before = count()
    for _ in range(12):
        assert run_bounded([sys.executable, "-c", "pass"], cwd=tmp_path, timeout=5).returncode == 0
    assert count() <= before + 1
