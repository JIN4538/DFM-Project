"""Fallback UI-state checks. This does not render a browser or take screenshots."""
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest

OUTPUT = Path(__file__).resolve().parent
CASES = {c["id"]: c["title"] for c in json.loads((ROOT / "examples/machining/manifest.json").read_text(encoding="utf-8"))}
snapshots = []


def capture(app, name):
    assert not app.exception, [(e.message, e.stack_trace) for e in app.exception]
    text = {kind: [e.value for e in getattr(app, kind)]
            for kind in ("title", "markdown", "caption", "warning", "info", "error")}
    figures = [json.loads(e.proto.spec) for e in app.get("plotly_chart")]
    snapshot = dict(name=name, utc=datetime.now(timezone.utc).isoformat(), text=text,
                    tables=[e.value.to_dict(orient="records") for e in app.dataframe],
                    figure_count=len(figures), download_count=len(app.get("download_button")),
                    code_revision=app.session_state["cnc_report"].get("code_revision") if "cnc_report" in app.session_state else None)
    snapshots.append(snapshot)
    (OUTPUT / f"{name}.plotly.json").write_text(json.dumps(figures, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT / "apptest_snapshots.json").write_text(json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8")
    return figures


def submit(app):
    next(button for button in app.button if button.label == "절삭 설계 검토").click().run()
    assert not app.exception
    return app.session_state["cnc_report"]


def finding(report, identifier):
    return next(f for f in report["findings"] if f["id"] == identifier)


app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
assert not app.exception
app.selectbox(key="manufacturing_family").select("절삭가공").run()
app.selectbox(key="source").select("절삭 검증 형상").run()
app.selectbox(key="cnc_example").select(CASES["01_rectangular_pocket"]).run()
app.number_input(key="cnc_diameter").set_value(8.)
app.number_input(key="cnc_flute").set_value(10.)
app.number_input(key="cnc_reach").set_value(15.)
report = submit(app)
pocket = finding(report, "cnc_rectangular_pockets")
assert pocket["status"] == "attention" and pocket["measurements"]["count"] == 1
assert pocket["face_indices"] and "반경" in pocket["action"]
app.selectbox(key="cnc_finding").select("cnc_rectangular_pockets").run()
capture(app, "01_rectangle_tool8")

app.selectbox(key="cnc_example").select(CASES["03_rounded_pocket"]).run()
assert not app.get("download_button")
report = submit(app)
corner = finding(report, "cnc_curved_corners")
assert corner["status"] == "attention" and len(corner["cad_face_ids"]) == 4 and corner["face_indices"]
assert all(row["radius_mm"] == 3 and row["tool_too_large"] for row in corner["measurements"]["cylindrical_faces"])
app.selectbox(key="cnc_finding").select("cnc_curved_corners").run()
capture(app, "02_rounded_tool8")
assert "예" in app.dataframe[0].value["공구 지름 > 특징 지름"].tolist()

app.number_input(key="cnc_diameter").set_value(4.)
report = submit(app)
corner = finding(report, "cnc_curved_corners")
assert corner["status"] == "observed" and not corner["cad_face_ids"] and not corner["face_indices"]
assert all(row["tool_too_large"] is False for row in corner["measurements"]["cylindrical_faces"])
app.selectbox(key="cnc_finding").select("cnc_curved_corners").run()
capture(app, "03_rounded_tool4")
assert "아니오" in app.dataframe[0].value["공구 지름 > 특징 지름"].tolist()
assert any("별도" in value for value in [x.value for x in app.caption])
assert any("원통형 엔드밀" in value for value in [x.value for x in app.markdown])

app.selectbox(key="cnc_example").select(CASES["10_plain_block"]).run()
app.checkbox(key="cnc_visibility").check()
report = submit(app)
assert report["visibility"]["status"] == "complete"
counts = report["visibility"]["measurements"]["sample_state_counts"]
assert counts["back_facing"] > 0 and counts["tangent"] > 0 and counts["visible"] > 0
app.selectbox(key="cnc_finding").select("cnc_visibility").run()
figures = capture(app, "04_block_visibility")
figure = figures[0]
assert figure["layout"]["showlegend"] is True
traces = {trace.get("name"): trace for trace in figure["data"]}
for label in ("공구 반대쪽을 향한 표본", "공구축과 평행한 면의 표본", "직선이 가려지지 않은 표본"):
    assert traces[label]["type"] == "scatter3d" and traces[label]["mode"] == "markers"
assert len({traces[label]["marker"]["symbol"] for label in traces if "표본" in str(label)}) >= 3

app.selectbox(key="manufacturing_family").select("적층제조").run()
assert not app.exception
assert any(button.label == "설계 검토" for button in app.button)
assert not any(button.label == "절삭 설계 검토" for button in app.button)
next(button for button in app.button if button.label == "설계 검토").click().run()
assert not app.exception and app.session_state["report"]["profile"]["process"] == "MEX"
capture(app, "05_additive_return")

result = dict(status="passed", check_type="Streamlit AppTest state and Plotly specification only",
              browser_visual_check="blocked_no_browser_provider", screenshots=[],
              narrow_and_wide_layout="not_verified", states=len(snapshots),
              finished_utc=datetime.now(timezone.utc).isoformat())
(OUTPUT / "apptest_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
