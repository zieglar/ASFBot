import logging

import pytest
import requests

import IPCProtocol as protocol_module
import logger


class FakeResponse:
    def __init__(self, data=None, *, status_code=200, json_error=None):
        self._data = data
        self.status_code = status_code
        self._json_error = json_error

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._data


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
        self.response = FakeResponse({"Success": True})
        self.error = None

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if self.error:
            raise self.error
        return self.response

    def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def sessions(monkeypatch):
    created = []
    def factory():
        session = FakeSession()
        created.append(session)
        return session
    test_logger = logging.getLogger("asfbot-test.protocol")
    monkeypatch.setattr(logger, "get_logger", lambda _name=None: test_logger)
    monkeypatch.setattr(protocol_module.requests, "Session", factory)
    return created


def test_get_and_post_use_explicit_configurable_timeout(sessions):
    handler = protocol_module.IPCProtocolHandler("asf", "1242", "/Api", connect_timeout=1.25, read_timeout=8.5)
    handler.get("/ASF", {"x": "y"})
    handler.post("/Command/", {"Command": "status ASF"})
    assert sessions[0].calls == [
        ("get", "http://asf:1242/Api/ASF", {"params": {"x": "y"}, "timeout": (1.25, 8.5), "allow_redirects": False}),
        ("post", "http://asf:1242/Api/Command/", {"json": {"Command": "status ASF"}, "timeout": (1.25, 8.5), "allow_redirects": False}),
    ]


@pytest.mark.parametrize("name,value", [
    ("connect_timeout", 0),
    ("read_timeout", -1),
    ("read_timeout", "slow"),
    ("connect_timeout", float("nan")),
    ("read_timeout", float("inf")),
    ("read_timeout", float("-inf")),
])
def test_timeout_values_must_be_positive_numbers(sessions, name, value):
    with pytest.raises((TypeError, ValueError), match="timeout"):
        protocol_module.IPCProtocolHandler("asf", "1242", **{name: value})


def test_authentication_header_is_instance_local_and_optional(sessions):
    authenticated = protocol_module.IPCProtocolHandler("asf", "1242", password="private")
    anonymous = protocol_module.IPCProtocolHandler("asf", "1242")
    assert sessions[0].headers["Authentication"] == "private"
    assert "Authentication" not in sessions[1].headers
    assert authenticated.headers is not anonymous.headers


@pytest.mark.parametrize(("error", "expected"), [
    (requests.ConnectTimeout("private detail"), "ASF IPC request timed out."),
    (requests.ReadTimeout("private detail"), "ASF IPC request timed out."),
    (requests.ConnectionError("private detail"), "Unable to connect to ASF IPC."),
])
def test_network_failures_have_stable_safe_messages(sessions, error, expected):
    handler = protocol_module.IPCProtocolHandler("asf", "1242")
    sessions[0].error = error
    assert handler.get("/ASF") == {"Success": False, "Message": expected}


def test_http_failure_has_stable_safe_message(sessions):
    handler = protocol_module.IPCProtocolHandler("asf", "1242")
    sessions[0].response = FakeResponse(status_code=503)
    assert handler.post("/Command/", {}) == {"Success": False, "Message": "ASF IPC returned HTTP 503."}


def test_invalid_json_has_stable_safe_message(sessions):
    handler = protocol_module.IPCProtocolHandler("asf", "1242")
    sessions[0].response = FakeResponse(json_error=ValueError("private response"))
    assert handler.get("/ASF") == {"Success": False, "Message": "ASF IPC returned invalid JSON."}


@pytest.mark.parametrize(("method", "argument"), [("get", []), ("post", [])])
def test_request_inputs_are_type_checked_without_assert(sessions, method, argument):
    handler = protocol_module.IPCProtocolHandler("asf", "1242")
    with pytest.raises(TypeError):
        getattr(handler, method)("/resource", argument)


def test_protocol_logs_no_password_payload_response_or_exception_details(sessions, caplog):
    password = "SENSITIVE-PASSWORD"
    command = "SENSITIVE-COMMAND"
    response_secret = "SENSITIVE-RESPONSE"
    exception_secret = "SENSITIVE-EXCEPTION"
    handler = protocol_module.IPCProtocolHandler("asf", "1242", password=password)
    sessions[0].response = FakeResponse({"Success": True, "Result": response_secret})
    with caplog.at_level(logging.DEBUG):
        handler.post("/Command/", {"Command": command})
        sessions[0].error = requests.ConnectionError(exception_secret)
        handler.get("/ASF", {"secret": command})
    for secret in (password, command, response_secret, exception_secret):
        assert secret not in caplog.text


@pytest.mark.parametrize("host", [
    "", "https://asf", "asf/path", "asf?query", "asf#fragment", "asf\ninternal",
    "999.999.999.999", ".asf", "asf..local", "-asf.local",
])
def test_rejects_unsafe_hosts(sessions, host):
    with pytest.raises(ValueError, match="host"):
        protocol_module.IPCProtocolHandler(host, "1242")


@pytest.mark.parametrize("port", ["", "abc", "0", 0, "65536", 65536, 12.5])
def test_rejects_invalid_ports(sessions, port):
    with pytest.raises((TypeError, ValueError), match="port"):
        protocol_module.IPCProtocolHandler("asf", port)


@pytest.mark.parametrize("path", ["Api", "/Api?x=1", "/Api#x", "/Api/../secret", "/Api\\secret", "/Api\nsecret"])
def test_rejects_unsafe_api_paths(sessions, path):
    with pytest.raises(ValueError, match="path"):
        protocol_module.IPCProtocolHandler("asf", "1242", path)


def test_normalizes_repeated_and_trailing_api_path_separators(sessions):
    handler = protocol_module.IPCProtocolHandler("asf", "1242", "//Api///")
    handler.get("//ASF")
    assert sessions[0].calls[0][1] == "http://asf:1242/Api/ASF"


@pytest.mark.parametrize("resource", [
    "ASF", "/Bot/../ASF", "/Bot/%2e%2e/ASF", "/Bot/%2FASF",
    "/ASF?password=x", "/ASF%3Fpassword=x", "/ASF#x", "/ASF\\x", "/ASF\rx",
])
def test_rejects_unsafe_resources(sessions, resource):
    handler = protocol_module.IPCProtocolHandler("asf", "1242")
    with pytest.raises(ValueError, match="resource"):
        handler.get(resource)


def test_redirect_is_not_followed_or_allowed_to_forward_authentication(sessions):
    handler = protocol_module.IPCProtocolHandler("asf", "1242", password="SENSITIVE-PASSWORD")
    sessions[0].response = FakeResponse(status_code=302)

    result = handler.get("/ASF")

    assert result == {"Success": False, "Message": "ASF IPC returned HTTP 302."}
    assert len(sessions[0].calls) == 1
    assert sessions[0].calls[0][2]["allow_redirects"] is False


def test_protocol_loggers_are_instance_local(sessions, monkeypatch):
    first_logger = logging.getLogger("asfbot-test.protocol.first")
    second_logger = logging.getLogger("asfbot-test.protocol.second")
    loggers = iter((first_logger, second_logger))
    monkeypatch.setattr(logger, "get_logger", lambda _name=None: next(loggers))

    first = protocol_module.IPCProtocolHandler("asf-one", "1242")
    second = protocol_module.IPCProtocolHandler("asf-two", "1242")

    assert first.log is first_logger
    assert second.log is second_logger
    assert not hasattr(protocol_module, "LOG")
