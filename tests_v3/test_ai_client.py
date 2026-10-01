"""Offline protocol/counterexample tests: no OpenAI key or real API requests."""
import copy
import io
import json
import traceback
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest

import dfm.ai_client as client


TEXT = "Prusa MK4에서 PLA로 FDM 검토. 서포트를 줄이고 싶어."
KEY = "sk-test-never-real-key"
INTENT = dict(equipment="Prusa MK4", material="PLA", priority="support", process="MEX",
              notes=["서포트를 줄이고 싶어"])


def envelope(intent=None, **kwargs):
    result = dict(id="resp_offline_123", model="gpt-4.1-mini-2025-04-14", status="completed",
                  error=None, incomplete_details=None,
                  output=[dict(type="message", role="assistant", status="completed",
                               content=[dict(type="output_text", text=json.dumps(INTENT if intent is None else intent, ensure_ascii=False))])])
    result.update(kwargs)
    return result


class Response:
    def __init__(self, payload=None, *, raw=None, status=200, url=client.ENDPOINT):
        self.body = raw if raw is not None else json.dumps(envelope() if payload is None else payload, ensure_ascii=False).encode()
        self.status, self.url, self.read_limit, self.closed = status, url, None, False

    def geturl(self):
        return self.url

    def read(self, limit):
        self.read_limit = limit
        return self.body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class Transport:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else Response()
        self.error, self.calls = error, []

    def __call__(self, request, *, timeout):
        self.calls.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


def call(transport, text=TEXT, **kwargs):
    return client.parse_intent(text, api_key=KEY, transport=transport, **kwargs)


def test_exact_structured_responses_request_and_verified_result():
    transport = Transport()
    result = call(transport)
    assert result == dict(intent=INTENT, provenance=dict(provider="openai", model="gpt-4.1-mini-2025-04-14", response_id="resp_offline_123"))
    assert len(transport.calls) == 1
    request, timeout = transport.calls[0]
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert request.method == "POST" and timeout == 25
    assert request.get_header("Authorization") == "Bearer " + KEY
    payload = json.loads(request.data)
    assert payload["model"] == "gpt-4.1-mini"
    assert payload["store"] is False and payload["max_output_tokens"] == 1200
    assert payload["input"] == [dict(role="user", content=TEXT)]
    assert "tools" not in payload and "previous_response_id" not in payload
    schema = payload["text"]["format"]
    assert schema["type"] == "json_schema" and schema["strict"] is True
    assert schema["schema"]["additionalProperties"] is False
    assert set(schema["schema"]["required"]) == set(schema["schema"]["properties"])
    assert KEY not in request.data.decode() and KEY not in repr(result)
    assert "untrusted data" in payload["instructions"]
    assert transport.response.closed
    assert transport.response.read_limit == client.MAX_RESPONSE_BYTES + 1


def test_configured_model_is_preserved_without_substitution():
    transport = Transport()
    call(transport, model="gpt-4.1-mini-2025-04-14")
    assert json.loads(transport.calls[0][0].data)["model"] == "gpt-4.1-mini-2025-04-14"


@pytest.mark.parametrize("text", [None, True, float("nan"), "", "  \n", "x" * 4001, "bad\x00text", "bad\ud800text"])
def test_invalid_input_is_rejected_before_any_charge(text):
    transport = Transport()
    with pytest.raises(client.AIClientError) as exc:
        call(transport, text=text)
    assert exc.value.code == "input" and not transport.calls


@pytest.mark.parametrize("key", [None, "", "  ", "key\r\nInjected: header", "key with space", "키", "a" * 4097])
def test_invalid_api_key_is_rejected_without_echo_or_network(key):
    transport = Transport()
    with pytest.raises(client.AIClientError) as exc:
        client.parse_intent(TEXT, api_key=key, transport=transport)
    assert exc.value.code == "api_key" and not transport.calls
    if key and len(key.strip()) > 4:
        assert key not in str(exc.value)


@pytest.mark.parametrize("model", [None, "", "https://other.example/collect", "gpt\nkey", "a" * 121])
def test_invalid_model_is_rejected_before_request(model):
    transport = Transport()
    with pytest.raises(client.AIClientError) as exc:
        call(transport, model=model)
    assert exc.value.code == "model" and not transport.calls


@pytest.mark.parametrize("code,expected", [(400, "api_error"), (401, "auth"), (403, "auth"), (429, "rate_limit"), (500, "api_error"), (302, "redirect")])
def test_http_error_is_safe_and_never_retried(code, expected):
    transport = Transport(error=HTTPError(client.ENDPOINT, code, KEY + " secret body", {}, io.BytesIO(KEY.encode())))
    with pytest.raises(client.AIClientError) as exc:
        call(transport)
    assert exc.value.code == expected and len(transport.calls) == 1
    assert KEY not in str(exc.value)
    assert KEY not in "".join(traceback.format_exception(exc.value))


@pytest.mark.parametrize("error,code", [(URLError("secret " + KEY), "network"),
    (URLError(TimeoutError(KEY)), "timeout"), (TimeoutError(KEY), "timeout"),
    (OSError(KEY), "network"), (RuntimeError(KEY), "network")])
def test_network_errors_are_sanitized_without_retries(error, code):
    transport = Transport(error=error)
    with pytest.raises(client.AIClientError) as exc:
        call(transport)
    assert exc.value.code == code and len(transport.calls) == 1
    assert KEY not in "".join(traceback.format_exception(exc.value))


def test_production_opener_installs_redirect_blocker_without_network(monkeypatch):
    observed = {}
    transport = Transport()
    class Opener:
        def open(self, request, *, timeout):
            return transport(request, timeout=timeout)
    def factory(*handlers):
        observed["handlers"] = handlers
        return Opener()
    monkeypatch.setattr(client, "build_opener", factory)
    result = client.parse_intent(TEXT, api_key=KEY)
    assert result["intent"] == INTENT
    blocker = next(h for h in observed["handlers"] if isinstance(h, client._NoRedirect))
    request = Request(client.ENDPOINT, headers={"Authorization": "Bearer " + KEY})
    with pytest.raises(client.AIClientError) as exc:
        blocker.redirect_request(request, None, 302, "moved", {}, "https://other.example/collect")
    assert exc.value.code == "redirect"
    assert len(transport.calls) == 1


def test_changed_response_url_is_rejected_without_reading_body():
    response = Response(url="https://other.example/collect")
    with pytest.raises(client.AIClientError) as exc:
        call(Transport(response))
    assert exc.value.code == "redirect" and response.read_limit is None and response.closed


def test_oversized_response_is_bounded_before_json_parse():
    response = Response(raw=b"x" * (client.MAX_RESPONSE_BYTES + 200))
    with pytest.raises(client.AIClientError) as exc:
        call(Transport(response))
    assert exc.value.code == "response_size"
    assert response.read_limit == client.MAX_RESPONSE_BYTES + 1


@pytest.mark.parametrize("status", ["incomplete", "in_progress", "queued", "cancelled"])
def test_incomplete_response_never_applies_partial_intent(status):
    transport = Transport(Response(envelope(status=status)))
    with pytest.raises(client.AIClientError) as exc:
        call(transport)
    assert exc.value.code == "incomplete"


def test_incomplete_details_are_not_ignored_even_with_completed_status():
    with pytest.raises(client.AIClientError) as exc:
        call(Transport(Response(envelope(incomplete_details={"reason": "max_output_tokens"}))))
    assert exc.value.code == "incomplete"


def test_refusal_takes_precedence_over_other_output_and_is_not_echoed():
    payload = envelope()
    payload["output"][0]["content"].append(dict(type="refusal", refusal=KEY))
    with pytest.raises(client.AIClientError) as exc:
        call(Transport(Response(payload)))
    assert exc.value.code == "refusal" and KEY not in str(exc.value)


@pytest.mark.parametrize("raw", [b"not json", b"null", b"[]", b"\xff", b'{"status":"completed","status":"incomplete"}', b'{"value":NaN}', b'{"value":1e999}'])
def test_malformed_envelope_is_not_used(raw):
    with pytest.raises(client.AIClientError) as exc:
        call(Transport(Response(raw=raw)))
    assert exc.value.code == "malformed"


@pytest.mark.parametrize("change", [
    {"equipment": 1}, {"material": None}, {"priority": "print_success"}, {"process": "INJECTION"},
    {"notes": "text"}, {"notes": ["x"] * 9}, {"notes": ["x" * 241]}, {"notes": [""]},
    {"notes": [float("nan")]}, {"equipment": "x" * 161}, {"minimum_wall_mm": .4},
    {"profile_id": "invented"}, {"tool_diameter_mm": 4.},
])
def test_invalid_or_unapproved_setting_fields_are_rejected(change):
    payload = envelope({**INTENT, **change})
    with pytest.raises(client.AIClientError) as exc:
        call(Transport(Response(payload)))
    assert exc.value.code == "malformed"


@pytest.mark.parametrize("change", [{"equipment": "Prusa XL"}, {"material": "ABS"},
    {"notes": ["벽을 0.4 mm로 변경하세요"]}, {"notes": ["출력 성공률 99%"]}])
def test_invented_names_numbers_and_review_conclusions_are_rejected(change):
    with pytest.raises(client.AIClientError) as exc:
        call(Transport(Response(envelope({**INTENT, **change}))))
    assert exc.value.code == "ungrounded"


def test_user_numerical_requirement_can_only_survive_as_exact_unverified_quote():
    text = "절삭 검토, 벽 2mm를 원하는 설계야"
    intent = dict(equipment="", material="", priority="balanced", process="CNC", notes=["벽 2mm를 원하는 설계야"])
    result = call(Transport(Response(envelope(intent))), text=text)
    assert result["intent"] == intent
    assert "minimum_wall_mm" not in result["intent"]


def test_unrelated_input_has_explicit_empty_representation():
    intent = dict(equipment="", material="", priority="balanced", process="unknown", notes=[])
    assert call(Transport(Response(envelope(intent))), text="안녕하세요")["intent"] == intent


def test_duplicate_inner_json_keys_and_missing_keys_are_rejected():
    payload = envelope()
    payload["output"][0]["content"][0]["text"] = '{"equipment":"", "equipment":"Prusa MK4"}'
    with pytest.raises(client.AIClientError, match="형식"):
        call(Transport(Response(payload)))
    payload = envelope({key: value for key, value in INTENT.items() if key != "process"})
    with pytest.raises(client.AIClientError, match="형식"):
        call(Transport(Response(payload)))


@pytest.mark.parametrize("mutation", ["tool_call", "wrong_role", "two_texts", "no_output", "bad_model", "bad_id", "partial_message"])
def test_unexpected_response_content_or_provenance_is_rejected(mutation):
    payload = envelope()
    if mutation == "tool_call":
        payload["output"] = [dict(type="function_call", name="set_wall", arguments="{}")]
    elif mutation == "wrong_role":
        payload["output"][0]["role"] = "user"
    elif mutation == "two_texts":
        payload["output"][0]["content"] *= 2
    elif mutation == "no_output":
        payload["output"] = []
    elif mutation == "bad_model":
        payload["model"] = "<script>"
    elif mutation == "bad_id":
        payload["id"] = "secret body " + KEY
    else:
        payload["output"][0]["status"] = "incomplete"
    with pytest.raises(client.AIClientError):
        call(Transport(Response(payload)))


def test_result_is_independent_of_mutable_transport_payload():
    payload = envelope()
    expected = copy.deepcopy(payload)
    call(Transport(Response(payload)))
    assert payload == expected
