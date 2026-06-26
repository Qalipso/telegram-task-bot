"""Phase 4 — the candidate/assignee methods exist on the real ApiClient and route through _request.

We do not hit the network: we stub `_request` and assert each method calls the right verb/path and
returns the parsed JSON. The error type is Phase 3's ConversationalApiError (NOT ApiError)."""
from aiwip_bot.api_client import ApiClient, ConversationalApiError


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _client_with_recorder(payload):
    client = ApiClient.__new__(ApiClient)  # bypass __init__/login; we only test the method surface
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return _Resp(payload)

    client._request = fake_request  # type: ignore[attr-defined]
    return client, calls


def test_get_candidate_calls_get_and_returns_json():
    client, calls = _client_with_recorder({"candidate": {"id": 5}, "assignees": [], "messages": []})
    out = client.get_candidate(5)
    assert out == {"candidate": {"id": 5}, "assignees": [], "messages": []}
    assert calls[0][0] == "GET" and calls[0][1] == "/api/candidates/5"


def test_approve_candidate_calls_post():
    client, calls = _client_with_recorder({"id": 1, "source_candidate_id": 5})
    out = client.approve_candidate(5)
    assert out == {"id": 1, "source_candidate_id": 5}
    assert calls[0][0] == "POST" and calls[0][1] == "/api/candidates/5/approve"


def test_reject_candidate_calls_post():
    client, calls = _client_with_recorder({"id": 5, "status": "rejected"})
    client.reject_candidate(5)
    assert calls[0][0] == "POST" and calls[0][1] == "/api/candidates/5/reject"


def test_patch_candidate_sends_payload():
    client, calls = _client_with_recorder({"id": 5, "status": "edited"})
    client.patch_candidate(5, {"assignee_ids": [11]})
    assert calls[0][0] == "PATCH" and calls[0][1] == "/api/candidates/5"
    assert calls[0][2]["json"] == {"assignee_ids": [11]}


def test_list_assignees_calls_get_with_active():
    client, calls = _client_with_recorder([{"id": 10, "display_name": "Alice"}])
    out = client.list_assignees(active=True)
    assert out == [{"id": 10, "display_name": "Alice"}]
    assert calls[0][0] == "GET" and calls[0][1] == "/api/assignees"
    assert calls[0][2]["params"] == {"active": "true"}


def test_conversational_api_error_is_the_error_type():
    # Phase 3's exception is ConversationalApiError(message, status_code) — there is no ApiError.
    err = ConversationalApiError("nope", status_code=404)
    assert err.status_code == 404
    assert "nope" in str(err)
