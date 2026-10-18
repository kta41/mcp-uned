import base64
import time

from uned_mcp import auth, client, config


def test_decode_token_base64():
    raw = base64.b64encode(b"1:::abcdef0123456789abcdef0123456789:::private").decode()
    assert auth.decode_token(raw) == "abcdef0123456789abcdef0123456789"


def test_decode_token_plain():
    assert auth.decode_token("abcdef0123456789abcdef0123456789") == "abcdef0123456789abcdef0123456789"


def test_find_token_in_html_with_padding():
    raw = base64.b64encode(b"1:::tok123456789012345678901234").decode()
    html = f'<a href="moodleappfs://token={raw}">open</a>'
    assert auth.find_token(html) == "tok123456789012345678901234"


def test_find_token_missing():
    assert auth.find_token("<html></html>") is None


def test_arr_encoding():
    assert client.arr("courseids", [5, 7]) == {"courseids[0]": 5, "courseids[1]": 7}


def test_assignments_sorted_by_timestamp(monkeypatch):
    now = int(time.time())
    data = {"courses": [{"id": 1, "assignments": [
        {"name": "late", "duedate": now + 40 * 86400},
        {"name": "soon", "duedate": now + 2 * 86400},
        {"name": "past", "duedate": now - 86400},
    ]}]}
    monkeypatch.setattr(client, "call", lambda *a, **k: data)
    out = client.upcoming_assignments([{"id": 1, "fullname": "C"}], 60)
    assert [o["tarea"] for o in out] == ["soon", "late"]


def test_get_courses_reports_course_error(monkeypatch):
    def fake(fn, **k):
        if fn == "core_webservice_get_site_info":
            return {"userid": 1}
        return {"error": "boom", "message": "x"}

    monkeypatch.setattr(client, "call", fake)
    try:
        client.get_courses()
    except RuntimeError as exc:
        assert "boom" in str(exc)
    else:
        raise AssertionError


def test_token_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "TOKEN_FILE", tmp_path / "token.json")
    client.save_auth({"token": "abc"})
    assert client.load_token() == "abc"
    assert oct(config.TOKEN_FILE.stat().st_mode)[-3:] == "600"


def test_find_token_custom_scheme():
    raw = base64.b64encode(b"site123:::tok123456789012345678901234").decode()
    assert auth.find_token(f"ltgopenlmsapp://token={raw}") == "tok123456789012345678901234"
