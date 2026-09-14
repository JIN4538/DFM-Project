"""Package tracked development files, excluding the original reference archives."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from amdfm.analysis import code_digest


def build(out):
    out.mkdir(parents=True,exist_ok=False)
    original=set(subprocess.check_output(["git","ls-tree","-r","--name-only","-z","1706eac"],cwd=ROOT).split(b"\0"))
    current=subprocess.check_output(["git","ls-files","-z"],cwd=ROOT).split(b"\0")
    files=[ROOT/n.decode("utf-8") for n in current if n and n not in original]
    manifest={"version":"3.0.0","created_utc":datetime.now(timezone.utc).isoformat(),
        "git_commit":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT).decode().strip(),
        "analysis_code_sha256":code_digest(),
        "scope":"Source distribution. Original PDF/DOCX/ZIP archives, external STL geometry, Python runtime and installed dependencies are not bundled.",
        "files":[{"path":p.relative_to(ROOT).as_posix(),"bytes":p.stat().st_size,
                  "sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
    payload=json.dumps(manifest,ensure_ascii=False,indent=2).encode("utf-8")
    target=out/"AM-DFM_v3_0_source.zip"
    with zipfile.ZipFile(target,"x",zipfile.ZIP_DEFLATED,compresslevel=7) as archive:
        for path in files:archive.write(path,"AM-DFM_v3_0/"+path.relative_to(ROOT).as_posix())
        archive.writestr("AM-DFM_v3_0/release_manifest.json",payload)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for item in manifest["files"]:
            assert hashlib.sha256(archive.read("AM-DFM_v3_0/"+item["path"])).hexdigest()==item["sha256"]
    (out/"release_manifest.json").write_bytes(payload)
    (out/"SHA256SUMS.txt").write_text(hashlib.sha256(target.read_bytes()).hexdigest()+"  "+target.name+"\n",encoding="utf-8")
    print(json.dumps({"zip":str(target),"files":len(files),"bytes":target.stat().st_size,"verified":True}))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    build(args.out.resolve())
