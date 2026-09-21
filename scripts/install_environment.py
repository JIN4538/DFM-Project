"""Install into this project only; preserve diagnostics and existing environments."""
from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = ((3, 12), (3, 13))


def install(*, diagnose=False):
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"install-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
    with log_path.open("x", encoding="utf-8") as log:
        def say(message):
            print(message, flush=True)
            log.write(str(message) + "\n")
            log.flush()

        def run(command):
            say("\n> " + subprocess.list2cmdline([str(x) for x in command]))
            environment = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=environment)
            for line in process.stdout:
                say(line.rstrip("\r\n"))
            code = process.wait()
            if code:
                raise RuntimeError(f"명령 실행 실패 (종료 코드 {code}). 위 오류와 로그를 확인하세요.")

        try:
            say("AM-DFM 실행환경 설치")
            say(f"프로젝트: {ROOT}")
            say(f"Python: {sys.executable} ({sys.version.split()[0]})")
            say(f"설치 로그: {log_path}")
            if sys.version_info[:2] not in SUPPORTED or sys.maxsize <= 2**32:
                raise RuntimeError("Python 3.12 또는 3.13의 64-bit 실행환경이 필요합니다.")
            if not (ROOT / "requirements.txt").is_file() or not (ROOT / "app.py").is_file():
                raise RuntimeError("requirements.txt 또는 app.py가 없습니다. ZIP 전체를 폴더에 압축 해제한 뒤 INSTALL.cmd를 실행하세요.")
            target = ROOT / ".venv"
            executable = target / "Scripts" / "python.exe"
            if target.exists():
                try:
                    probe = subprocess.run([str(executable), "-c",
                        "import sys; sys.exit(sys.version_info[:2] not in ((3,12),(3,13)) or sys.maxsize <= 2**32)"],
                        capture_output=True, timeout=15)
                    valid = probe.returncode == 0
                except (OSError, subprocess.TimeoutExpired):
                    valid = False
                if not valid:
                    raise RuntimeError("기존 .venv를 실행할 수 없습니다. 기존 폴더는 보존했습니다. ZIP을 새 폴더에 풀어 설치하세요.")
                say("기존 정상 .venv를 재사용합니다.")
            else:
                say("이 폴더에 새 .venv를 생성합니다. 시스템 Python 패키지는 변경하지 않습니다.")
            if diagnose:
                say("[DIAGNOSE] 진단 완료. 설치 또는 패키지 변경은 수행하지 않았습니다.")
                return 0
            if not target.exists():
                run([sys.executable, "-m", "venv", str(target)])
            run([str(executable), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(ROOT / "requirements.txt")])
            run([str(executable), "-m", "pip", "check"])
            run([str(executable), "-c", "import streamlit, trimesh, numpy, scipy, shapely, pandas, rtree, manifold3d, plotly; from OCP.STEPControl import STEPControl_Reader; print('Application and STEP imports: OK')"])
            say("\n설치 완료. START_REVIEW.cmd를 실행하세요.")
            return 0
        except (OSError, RuntimeError, KeyboardInterrupt) as exc:
            say(f"\n[FAILED] {exc}")
            say(f"로그 보관 위치: {log_path}")
            return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--no-pause", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        raise SystemExit(install(diagnose=args.diagnose))
    except OSError as exc:
        print(f"[FAILED] 설치 경로 또는 로그 폴더를 열 수 없습니다: {exc}", flush=True)
        raise SystemExit(1)
