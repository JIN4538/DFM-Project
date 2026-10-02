"""Start the local review app, or open the same healthy Windows server again."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser


def windows_arguments(command: str) -> list[str]:
    """Parse native argv quoting, including Korean and space-containing paths."""
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    shell.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    shell.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    argv = shell.CommandLineToArgvW(command, ctypes.byref(count))
    if not argv:
        raise OSError(ctypes.get_last_error(), "Cannot read process arguments")
    try:
        return [argv[i] for i in range(count.value)]
    finally:
        kernel.LocalFree(argv)


def is_this_app(arguments: list[str], app: Path, python: Path, base_python: Path | None = None) -> bool:
    # Windows venv redirectors can expose the base interpreter in the child's argv.
    allowed = {python.resolve()}
    if base_python is not None:
        allowed.add(base_python.resolve())
    if not arguments or Path(arguments[0]).resolve() not in allowed:
        return False
    # Accept Python's UTF-8 interpreter option, then require the exact module.
    index = 1
    if arguments[index:index + 2] == ["-X", "utf8"]:
        index += 2
    if arguments[index:index + 3] != ["-m", "streamlit", "run"]:
        return False
    index += 3
    if index >= len(arguments):
        return False
    entry = Path(arguments[index])
    # A relative filename cannot prove the working directory of another process.
    return entry.is_absolute() and entry.resolve() == app.resolve()


def listener_commands(port: int) -> list[dict]:
    if os.name != "nt":
        return []
    command = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "$ErrorActionPreference='Stop'; "
        f"$owners = @(Get-NetTCPConnection -State Listen -LocalPort {int(port)} "
        "-ErrorAction SilentlyContinue | Where-Object { "
        "$_.LocalAddress -eq '127.0.0.1' -or $_.LocalAddress -eq '0.0.0.0' "
        "-or $_.LocalAddress -eq '::' } | "
        "Select-Object -ExpandProperty OwningProcess -Unique); "
        "@($owners | ForEach-Object { Get-CimInstance Win32_Process "
        "-Filter ('ProcessId=' + $_) | Select-Object ProcessId,CommandLine }) "
        "| ConvertTo-Json -Compress"
    )
    powershell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    result = subprocess.run(
        [str(powershell), "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, encoding="utf-8", errors="replace", timeout=8,
        creationflags=subprocess.CREATE_NO_WINDOW, check=True,
    )
    data = json.loads(result.stdout.strip() or "[]")
    return [data] if isinstance(data, dict) else data


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if os.name == "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def healthy(url: str) -> bool:
    try:
        # Local checks must not be sent through a configured external HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "_stcore/health", timeout=1) as response:
            return response.status == 200 and response.read(16).strip() == b"ok"
    except (OSError, ValueError):
        return False


def reuse(app: Path, python: Path, port: int, *, no_browser: bool) -> bool:
    try:
        owners = listener_commands(port)
        if not owners or not all(
            is_this_app(windows_arguments(owner.get("CommandLine") or ""), app, python,
                        Path(getattr(sys, "_base_executable", sys.executable)))
            for owner in owners
        ):
            return False
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    url = f"http://127.0.0.1:{port}/"
    for attempt in range(10):
        if healthy(url):
            print(f"AM-DFM is already running. Opening {url}", flush=True)
            if not no_browser:
                try:
                    if not webbrowser.open(url):
                        print(f"Open this address in your browser: {url}", flush=True)
                except (OSError, webbrowser.Error):
                    print(f"Open this address in your browser: {url}", flush=True)
            return True
        if attempt < 9:
            time.sleep(0.2)
    return False


def main(argv=None, *, root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8507)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535")
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    app = root / "app.py"
    python = Path(sys.executable).resolve()
    if not app.is_file():
        print(f"Missing app file: {app}", flush=True)
        return 1
    if not port_available(args.port):
        if reuse(app, python, args.port, no_browser=args.no_browser):
            return 0
        print(
            f"Port {args.port} is occupied; a healthy server for this AM-DFM folder "
            "could not be confirmed.\n"
            "No running program was stopped. You can use another port, for example:\n"
            f"START_REVIEW.cmd --port {8508 if args.port != 8508 else 8509}",
            flush=True,
        )
        return 1
    print(f"Starting AM-DFM: http://127.0.0.1:{args.port}/", flush=True)
    try:
        result = subprocess.call(
            [str(python), "-X", "utf8", "-m", "streamlit", "run", str(app),
             "--server.address", "127.0.0.1", "--server.port", str(args.port),
             "--server.headless", "true" if args.no_browser else "false"],
            cwd=root,
        )
    except KeyboardInterrupt:
        return 0
    except OSError as error:
        print(f"Could not start AM-DFM: {error}", flush=True)
        return 1
    # Two near-simultaneous clicks may both have observed a free port.
    if result and reuse(app, python, args.port, no_browser=args.no_browser):
        return 0
    return result


if __name__ == "__main__":
    raise SystemExit(main())
