"""Choose measured alternatives exactly, after learned proposal generation.

The policy is the disclosed training target, not a learned expert label. The
ranker's predictions are retained for audit, but cannot introduce arithmetic
approximation error into the final choice. Explicit local preferences remain a
learned residual, behind the same geometry and conflict gates.
"""
from copy import deepcopy
import math

from . import plan_learning as prior

POLICY_VERSION = "verified-tradeoff-1"


def selection_score(features):
    """Exact counterpart of the frozen plan-ranker training objective."""
    if len(features) != len(prior.FEATURES) or any(
        type(x) not in (int, float) or not math.isfinite(x) for x in features
    ) or any(not 0 <= x <= 1 for i, x in enumerate(features)
             if not (features[0] == 0 and 1 <= i <= 3)):
        raise ValueError("비교할 측정값을 확인하세요")
    if features[0] == 0:
        weights = [(3. if features[8+i] else 1.) * features[14+i] for i in range(3)]
        total = sum(weights)
        if total == 0:
            return 0.
        values = [features[1+i]*weights[i] for i in range(3)]
        return -(.7*max(values)/max(weights) + .3*sum(values)/total)
    g, t, slender, changes = features[4:8]
    weights = (4., 1., 1.5) if features[11] else (1., 1., 3.) if features[13] else (2., 1., 2.)
    a, b, c = [v*w for v, w in zip((g, t, slender), weights)]
    return -(.5*max(a, b, c)/max(weights) + .35*(a+b+c)/sum(weights)
             + .1*g*slender + .05*changes)


def include_current_direction(report):
    """Keep a valid custom direction eligible even when it is a trade-off.

    A current direction need not Pareto-dominate a search direction to be the
    best compromise. The input report remains unchanged.
    """
    fields = prior.AM_FIELDS.get(prior._process(report))
    if not fields:
        return report
    current = report.get("current_orientation") or {}
    direction = current.get("direction") or []
    if len(direction) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in direction):
        return report
    if math.sqrt(sum(v*v for v in direction)) <= 1e-12:
        return report
    if any(type(current.get(f)) not in (int, float) or not math.isfinite(current[f]) or current[f] < 0 for f in fields):
        return report
    if report.get("profile", {}).get("build_volume_mm") is not None and current.get("build_fit") is not True:
        return report
    rows = report.get("orientations", [])
    def same_direction(row):
        other = row.get("direction") or []
        return len(other) == 3 and all(math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)
                                      for a, b in zip(direction, other))
    if any(same_direction(row) and row.get("candidate_role", "search") == "search" for row in rows):
        return report
    updated = deepcopy(report)
    row = deepcopy(current)
    row.update(name="현재 사용자 방향", candidate_role="search", proposal_source="measured_current")
    updated["orientations"] = [*updated.get("orientations", []), row]
    return updated


def _current_orientation(report, selected):
    if selected["family"] != "AM" or not selected["keep_current"]:
        return
    actual = deepcopy(report.get("current_orientation") or {})
    direction = actual.get("direction") or []
    matching = next((r.get("name") for r in report.get("orientations", [])
                     if len(direction) == len(r.get("direction") or []) == 3
                     and all(math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)
                             for a, b in zip(direction, r["direction"]))), None)
    actual["name"] = matching or actual.get("name") or "현재 방향"
    selected["orientation"] = actual


def arbitrate(report, result, *, preferences=None, feedback_path=None, normalization_report=None):
    """Common measured policy for existing and learned sequential proposals."""
    if not result.get("ranking"):
        return result
    prefs = prior._preferences(report, preferences)
    output = deepcopy(result)
    plans, rejected = [], []
    cnc = prior._process(report) in ("CNC", "MILLING_3AXIS")
    criteria = []
    if not cnc:
        from amdfm.recommendation import recommend_orientation
        criteria = recommend_orientation(normalization_report or report).get("criteria", [])
    for old in output["ranking"]:
        plan = deepcopy(old)
        try:
            if cnc:
                from .rl_planner import evaluate_changes
                assessed = evaluate_changes(report, plan["changes"], preferences=prefs)
                checked = assessed["plan"]
                for key in ("remaining", "remaining_finding_ids", "covered_finding_ids", "outcomes", "_metrics",
                            "_dominance", "_baseline", "planning_cost", "keep_current", "verified", "conflict_details"):
                    plan[key] = checked[key]
            plan["_features"] = prior._features(plan, prefs)
            exact_features = list(plan["_features"])
            if not cnc and criteria:
                # Adding a custom current direction must not rescale the fixed
                # search. Its genuine out-of-range advantage is not clipped.
                slots = {"overhang_projected_area_sum_mm2": 1, "height_mm": 2, "contact_triangle_area_mm2": 3}
                for criterion in criteria:
                    value = plan["outcomes"][criterion["field"]]
                    low, high = criterion["minimum"], criterion["maximum"]
                    if criterion["constant"]:
                        regret = (value-low)/max(1., abs(low), abs(value))
                    else:
                        regret = (value-low)/(high-low)
                    if criterion["direction"] == "max":
                        regret = -regret if criterion["constant"] else 1-regret
                    exact_features[slots[criterion["field"]]] = regret
                plan["_features"] = [max(0., min(1., x)) for x in exact_features]
            plan["exact_score"] = selection_score(exact_features)
            plan["learned_score"] = plan.get("prior_score")
            plans.append(plan)
        except (ValueError, KeyError, TypeError, OverflowError, IndexError):
            rejected.append(plan.get("id"))
    if not plans:
        output.update(status="unavailable", selected=None, alternatives=[], ranking=[],
                      reason="개선안의 치수 재검산을 완료할 수 없습니다")
        return output
    minimum_conflicts = min(p["outcomes"]["remaining_numeric_conflicts"] for p in plans) if cnc else None
    if cnc:
        plans = [p for p in plans if p["outcomes"]["remaining_numeric_conflicts"] == minimum_conflicts]
    plans = [p for p in plans if not any(prior._dominates(other, p) for other in plans if other is not p)]
    try:
        feedback = prior._read_feedback(prior._feedback_path(feedback_path))["scopes"].get(prior._scope(report, prefs), {})
    except (OSError, ValueError, KeyError, TypeError):
        feedback = {}
    weights = feedback.get("weights", [0.]*len(prior.FEATURES))
    for plan in plans:
        plan["preference_score"] = sum(w*x for w, x in zip(weights, plan["_features"]))
        plan["score"] = plan["exact_score"] + plan["preference_score"]
    plans.sort(key=lambda p: (-round(p["score"], 9), not p["keep_current"], prior._stable(p)))
    selected = plans[0]
    _current_orientation(report, selected)
    old_id = (result.get("selected") or {}).get("id")
    output.update(selected=selected, ranking=plans, alternatives=plans[1:],
                  status="keep" if selected["keep_current"] else "recommended",
                  selection_source="verified_policy+preference" if feedback.get("choices", 0) else "verified_policy",
                  selection_changed=selected["id"] != result.get("baseline_selected_id"), reason="",
                  verified_selection=dict(version=POLICY_VERSION, predicted_selected_id=old_id,
                                          final_selected_id=selected["id"], corrected=old_id != selected["id"],
                                          minimum_numeric_conflicts=minimum_conflicts, rejected_candidate_ids=rejected,
                                          exact_score=selected["exact_score"], preference_score=selected["preference_score"]))
    if cnc and selected["keep_current"] and minimum_conflicts > 0:
        output.update(status="unavailable", selected=None,
                      reason="허용한 변경 범위에서는 충돌을 줄일 수 없습니다. 형상 또는 공구 변경을 허용하세요.")
    return output
