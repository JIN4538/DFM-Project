"""Bound owned workers and descendants, including Windows venv launchers.

Windows uses a private, non-inherited Job Object with kill-on-close and no
breakaway. The primary thread starts suspended, is assigned, then resumed.
Sources: Microsoft Job Objects; AssignProcessToJobObject; Process Creation Flags;
ResumeThread; JOBOBJECT_EXTENDED_LIMIT_INFORMATION. See timeout audit notes.
"""
from __future__ import annotations

import math
import os
import signal
import subprocess
import tempfile
import time


_CLEANUP_SECONDS = 5.0


class _WindowsJob:
    """One unnamed job; no PID discovery or access to unrelated processes."""

    def __init__(self):
        import ctypes as ct
        from ctypes import wintypes as wt

        class BasicLimits(ct.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ct.c_longlong), ("PerJobUserTimeLimit", ct.c_longlong),
                        ("LimitFlags", wt.DWORD), ("MinimumWorkingSetSize", ct.c_size_t),
                        ("MaximumWorkingSetSize", ct.c_size_t), ("ActiveProcessLimit", wt.DWORD),
                        ("Affinity", ct.c_size_t), ("PriorityClass", wt.DWORD), ("SchedulingClass", wt.DWORD)]

        class IOCounters(ct.Structure):
            _fields_ = [(name, ct.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(ct.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IOCounters),
                        ("ProcessMemoryLimit", ct.c_size_t), ("JobMemoryLimit", ct.c_size_t),
                        ("PeakProcessMemoryUsed", ct.c_size_t), ("PeakJobMemoryUsed", ct.c_size_t)]

        class Accounting(ct.Structure):
            _fields_ = [(name, ct.c_longlong) for name in (
                "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime")]
            _fields_ += [(name, wt.DWORD) for name in (
                "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")]

        self.ct, self.Accounting = ct, Accounting
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ct.c_void_p, wt.LPCWSTR], wt.HANDLE),
            "SetInformationJobObject": ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD], wt.BOOL),
            "AssignProcessToJobObject": ([wt.HANDLE, wt.HANDLE], wt.BOOL),
            "QueryInformationJobObject": ([wt.HANDLE, ct.c_int, ct.c_void_p, wt.DWORD, ct.c_void_p], wt.BOOL),
            "TerminateJobObject": ([wt.HANDLE, wt.UINT], wt.BOOL),
            "ResumeThread": ([wt.HANDLE], wt.DWORD),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ct.WinError(ct.get_last_error())
        try:
            limits = ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            self._check(self.kernel.SetInformationJobObject(self.handle, 9, ct.byref(limits), ct.sizeof(limits)))
        except BaseException:
            self.close()
            raise

    def _check(self, success):
        if not success:
            raise self.ct.WinError(self.ct.get_last_error())

    def assign(self, process):
        self._check(self.kernel.AssignProcessToJobObject(self.handle, process))

    def resume(self, thread):
        previous = self.kernel.ResumeThread(thread)
        if previous == 0xFFFFFFFF:
            raise self.ct.WinError(self.ct.get_last_error())
        if previous != 1:
            raise OSError("작업자의 초기 일시중지 상태를 확인하지 못했습니다.")

    def active(self):
        value = self.Accounting()
        self._check(self.kernel.QueryInformationJobObject(
            self.handle, 1, self.ct.byref(value), self.ct.sizeof(value), None))
        return value.ActiveProcesses

    def wait_empty(self, timeout):
        deadline = time.monotonic() + timeout
        while self.active():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(.02, remaining))
        return True

    def terminate(self):
        self._check(self.kernel.TerminateJobObject(self.handle, 1))

    def close(self):
        import _winapi
        if self.handle is not None:
            _winapi.CloseHandle(self.handle)
            self.handle = None


def _cleanup_windows(job, process, thread, inherited, *, quiescent):
    """Attempt every owned cleanup even when one operation fails; never wait forever."""
    import _winapi
    failures = []

    def attempt(operation):
        try:
            operation()
        except BaseException as exc:
            failures.append(exc)

    if not quiescent:
        terminated = False
        try:
            job.terminate()
            terminated = True
        except BaseException as exc:
            failures.append(exc)
        if terminated:
            def wait_for_owned_children():
                if not job.wait_empty(_CLEANUP_SECONDS):
                    raise OSError("작업자 후손 종료를 제한 시간 안에 확인하지 못했습니다.")
            attempt(wait_for_owned_children)
    # Closing the final non-inherited job handle is also a kill fallback.
    attempt(job.close)
    if process is not None:
        def stop_direct_process():
            if _winapi.WaitForSingleObject(process, 0) != _winapi.WAIT_OBJECT_0:
                try:
                    _winapi.TerminateProcess(process, 1)
                except PermissionError:
                    # TerminateJobObject may already be tearing down this
                    # process before its handle becomes signalled.
                    if _winapi.WaitForSingleObject(process, int(_CLEANUP_SECONDS*1000)) != _winapi.WAIT_OBJECT_0:
                        raise
                if _winapi.WaitForSingleObject(process, int(_CLEANUP_SECONDS*1000)) != _winapi.WAIT_OBJECT_0:
                    raise OSError("작업자 프로세스 종료를 확인하지 못했습니다.")
        attempt(stop_direct_process)
    for handle in [thread, *inherited, process]:
        if handle is not None:
            attempt(lambda h=handle: _winapi.CloseHandle(h))
    if failures:
        raise OSError("작업자 격리/정리 실패: " + "; ".join(str(e) for e in failures)) from failures[0]


def _run_windows(args, *, cwd, timeout):
    import _winapi
    import msvcrt

    deadline = time.monotonic() + timeout
    job = _WindowsJob()
    process = thread = None
    inherited = []
    quiescent = False
    try:
        # Regular files cannot deadlock on pipes held by a surviving descendant.
        # They stay private and are read only after every process in the job exits.
        with open(os.devnull, "rb") as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            current = _winapi.GetCurrentProcess()
            for file in (stdin, stdout, stderr):
                inherited.append(_winapi.DuplicateHandle(current, msvcrt.get_osfhandle(file.fileno()),
                    current, 0, True, _winapi.DUPLICATE_SAME_ACCESS))
            startup = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESTDHANDLES,
                hStdInput=inherited[0], hStdOutput=inherited[1], hStdError=inherited[2],
                lpAttributeList={"handle_list": inherited})
            command = args if isinstance(args, str) else subprocess.list2cmdline(
                [args] if isinstance(args, (bytes, os.PathLike)) else args)
            # CPython's CreateProcess wrapper retains the primary thread handle;
            # Popen closes it before callers can assign a job and resume safely.
            process, thread, _, _ = _winapi.CreateProcess(None, command, None, None, True,
                subprocess.CREATE_NO_WINDOW | 0x4, None, os.fsdecode(cwd) if cwd is not None else None, startup)
            job.assign(process)
            job.resume(thread)
            timed_out = not job.wait_empty(max(0., deadline-time.monotonic()))
            if timed_out:
                job.terminate()
                if not job.wait_empty(_CLEANUP_SECONDS):
                    raise OSError("시간 제한 후 작업자 종료를 확인하지 못했습니다.")
            if _winapi.WaitForSingleObject(process, int(_CLEANUP_SECONDS*1000)) != _winapi.WAIT_OBJECT_0:
                raise OSError("작업자 종료 신호를 제한 시간 안에 확인하지 못했습니다.")
            quiescent = True
            returncode = _winapi.GetExitCodeProcess(process)
            stdout.seek(0)
            stderr.seek(0)
            output, errors = stdout.read(), stderr.read()
            if timed_out:
                raise subprocess.TimeoutExpired(args, timeout, output=output, stderr=errors)
            return subprocess.CompletedProcess(args, returncode, output, errors)
    finally:
        _cleanup_windows(job, process, thread, inherited, quiescent=quiescent)


def run_bounded(args, *, cwd, timeout):
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("작업 시간 제한은 유한한 양수여야 합니다.")
    if os.name == "nt":
        return _run_windows(args, cwd=cwd, timeout=timeout)
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          cwd=cwd, start_new_session=True) as proc:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if proc.poll() is None:
                proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=_CLEANUP_SECONDS)
            except subprocess.TimeoutExpired as exc:
                raise OSError("작업자 출력 정리가 제한 시간 안에 완료되지 않았습니다.") from exc
            raise subprocess.TimeoutExpired(args, timeout, output=stdout, stderr=stderr)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
