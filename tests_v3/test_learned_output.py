from dfm.learned_output import learned_html


def test_export_escapes_every_model_string_and_keeps_unknown():
    output = learned_html({"status": "partial", "model": {"id": "<script>x</script>"}, "items": [
        {"finding_id": "wall", "label": "벽", "state": "confirmed", "origin": "rule_fallback",
         "title": "<img onerror=x>", "action": "<script>x</script>", "evidence": ["1 < 2"]},
        {"finding_id": "cavities", "label": "공동", "state": "unavailable", "origin": "unavailable"}]})
    assert "<script>" not in output and "<img " not in output
    assert "&lt;script&gt;" in output and "1 &lt; 2" in output
    assert "미검토" in output and "rule_fallback" in output


def test_missing_model_is_not_presented_as_a_clear_judgment():
    assert learned_html(None) == ""
    output = learned_html({"status": "unavailable", "items": []})
    assert "검토 결과가 없습니다" in output and "수정 후보가 없습니다" not in output
    assert "검토했습니다" not in output
