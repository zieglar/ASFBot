import logging

import pytest

import ASFConnector as connector_module
import logger


@pytest.fixture(autouse=True)
def configured_logger(monkeypatch):
    test_logger = logging.getLogger("asfbot-test.connector")
    monkeypatch.setattr(logger, "get_logger", lambda _name=None: test_logger)


class FakeHandler:
    def __init__(self, *, get_response=None, post_response=None):
        self.get_response = get_response
        self.post_response = post_response
        self.calls = []

    def get(self, resource, parameters=None):
        self.calls.append(("get", resource, parameters))
        return self.get_response

    def post(self, resource, payload=None):
        self.calls.append(("post", resource, payload))
        return self.post_response


def make_connector(handler):
    connector = connector_module.ASFConnector()
    connector.connection_handler = handler
    return connector


def test_get_asf_info_uses_current_api_endpoint():
    response = {"Success": True, "Result": {"Version": "6.x"}}
    handler = FakeHandler(get_response=response)
    assert make_connector(handler).get_asf_info() == response
    assert handler.calls == [("get", "/ASF", None)]


def test_get_bot_info_formats_representative_farming_state():
    handler = FakeHandler(get_response={"Success": True, "Result": {"main": {
        "IsConnectedAndLoggedOn": True,
        "CardsFarmer": {
            "Paused": False,
            "CurrentGamesFarming": [{"AppID": 10, "GameName": "Example Game", "CardsRemaining": 2}],
            "GamesToFarm": [{"AppID": 20, "GameName": "Queued Game"}],
            "TimeRemaining": "01:02:03",
        },
    }}})
    result = make_connector(handler).get_bot_info("main")
    assert "Bot main:" in result
    assert "[10/Example Game] 2 cards remaining." in result
    assert "[20/Queued Game]" in result
    assert "Time remaining: 01:02:03" in result
    assert handler.calls == [("get", "/Bot/main", None)]


@pytest.mark.parametrize(("response", "expected"), [
    ({"Success": True}, "Bot missing not found."),
    ({"Success": False, "Message": "service unavailable"}, "Getting bot info failed: service unavailable"),
    ({"Success": True, "Result": {"main": {}}}, "Bot main: Offline.\n"),
])
def test_get_bot_info_handles_missing_fields_without_crashing(response, expected):
    assert make_connector(FakeHandler(get_response=response)).get_bot_info("missing") == expected


def test_bot_redeem_formats_result_and_current_api_payload():
    test_key = "TEST1-TEST2-TEST3"
    handler = FakeHandler(post_response={"Success": True, "Result": {
        "main": {test_key: {"Result": "OK", "PurchaseResultDetail": "NoDetail"}}
    }})
    message = make_connector(handler).bot_redeem("main", test_key)
    assert test_key in message
    assert "OK/NoDetail" in message
    assert handler.calls == [("post", "/Bot/main/Redeem", {"KeysToRedeem": [test_key]})]


def test_bot_redeem_accepts_a_set_and_sorts_it_for_stable_requests():
    handler = FakeHandler(post_response={"Success": True, "Result": {}})
    make_connector(handler).bot_redeem("main", {"KEY-B", "KEY-A"})
    assert handler.calls[0][2] == {"KeysToRedeem": ["KEY-A", "KEY-B"]}


def test_bot_redeem_rejects_invalid_key_container_without_assert():
    with pytest.raises(TypeError, match="keys"):
        make_connector(FakeHandler()).bot_redeem("main", ["KEY"])


def test_send_command_uses_current_api_endpoint_and_formats_response():
    handler = FakeHandler(post_response={"Success": True, "Result": "command result"})
    assert make_connector(handler).send_command("status ASF") == "command result"
    assert handler.calls == [("post", "/Command/", {"Command": "status ASF"})]


def test_connector_logs_neither_keys_commands_payloads_nor_responses(caplog):
    test_key = "SENSITIVE-TEST-KEY"
    command = "redeem main SENSITIVE-COMMAND"
    private_response = "SENSITIVE-ASF-RESPONSE"
    handler = FakeHandler(post_response={"Success": True, "Result": {
        "main": {test_key: {"Result": "OK", "PurchaseResultDetail": "NoDetail"}}
    }})
    connector = make_connector(handler)
    with caplog.at_level(logging.DEBUG):
        connector.bot_redeem("main", test_key)
        handler.post_response = {"Success": True, "Result": private_response}
        connector.send_command(command)
    assert test_key not in caplog.text
    assert command not in caplog.text
    assert private_response not in caplog.text


@pytest.mark.parametrize("selector", ["", "main/ASF", "main?x=1", "main#x", "main\nother", "main,,other"])
def test_bot_selector_rejects_path_query_fragment_and_empty_names(selector):
    connector = make_connector(FakeHandler(get_response={"Success": True}))
    with pytest.raises(ValueError, match="bot"):
        connector.get_bot_info(selector)


def test_bot_selector_preserves_comma_selectors_and_url_encodes_names():
    handler = FakeHandler(get_response={"Success": True})
    make_connector(handler).get_bot_info("main bot,secondary")
    assert handler.calls == [("get", "/Bot/main%20bot,secondary", None)]


@pytest.mark.parametrize("command", ["", "   ", None, 123])
def test_send_command_rejects_empty_or_invalid_input(command):
    with pytest.raises((TypeError, ValueError), match="command"):
        make_connector(FakeHandler()).send_command(command)


@pytest.mark.parametrize("keys", ["", "   ", set(), {"GOOD", ""}, {"GOOD", 1}, None])
def test_redeem_rejects_empty_or_invalid_keys(keys):
    with pytest.raises((TypeError, ValueError), match="keys"):
        make_connector(FakeHandler()).bot_redeem("main", keys)


@pytest.mark.parametrize("response", [
    {"Success": True, "Result": None},
    {"Success": True, "Result": []},
    {"Success": True, "Result": {"main": None}},
    {"Success": True, "Result": {"main": {"IsConnectedAndLoggedOn": True, "CardsFarmer": None}}},
    {"Success": True, "Result": {"main": {"IsConnectedAndLoggedOn": True, "CardsFarmer": {
        "CurrentGamesFarming": {}, "GamesToFarm": "bad", "TimeRemaining": None,
    }}}},
])
def test_get_bot_info_handles_malformed_results(response):
    message = make_connector(FakeHandler(get_response=response)).get_bot_info("main")
    assert isinstance(message, str)
    assert message


@pytest.mark.parametrize("response", [
    {"Success": True, "Result": None},
    {"Success": True, "Result": []},
    {"Success": True, "Result": {"main": None}},
    {"Success": True, "Result": {"main": {"KEY": None}}},
    {"Success": True, "Result": {"main": {"KEY": {"Result": 999, "PurchaseResultDetail": 999}}}},
    {"Success": True, "Result": {"main": {"KEY": {"purchase_receipt_info": {
        "line_items": None, "purchase_status": 999, "result_detail": 999,
    }}}}},
])
def test_bot_redeem_handles_malformed_results_and_unknown_enums(response):
    message = make_connector(FakeHandler(post_response=response)).bot_redeem("main", "KEY")
    assert isinstance(message, str)
    assert message


@pytest.mark.parametrize("invalid_value", [
    ["SENSITIVE-LIST-VALUE"],
    {"secret": "SENSITIVE-DICT-VALUE"},
])
@pytest.mark.parametrize("receipt", [False, True])
def test_bot_redeem_handles_unhashable_enum_values_without_echoing_them(invalid_value, receipt):
    if receipt:
        details = {"purchase_receipt_info": {
            "line_items": [],
            "purchase_status": invalid_value,
            "result_detail": invalid_value,
        }}
    else:
        details = {"Result": invalid_value, "PurchaseResultDetail": invalid_value}
    response = {"Success": True, "Result": {"main": {"KEY": details}}}

    message = make_connector(FakeHandler(post_response=response)).bot_redeem("main", "KEY")

    assert "Unknown value" in message
    assert "SENSITIVE" not in message


@pytest.mark.parametrize("response", [None, [], "text", 7, True])
def test_send_command_handles_non_dictionary_json(response):
    handler = FakeHandler(post_response=response)
    assert make_connector(handler).send_command("status ASF") == (
        "Command unsuccessful: Invalid ASF response."
    )


def test_connector_loggers_are_instance_local(monkeypatch):
    first_logger = logging.getLogger("asfbot-test.connector.first")
    second_logger = logging.getLogger("asfbot-test.connector.second")
    loggers = iter((first_logger, second_logger))
    monkeypatch.setattr(logger, "get_logger", lambda _name=None: next(loggers))
    monkeypatch.setattr(connector_module, "IPCProtocolHandler", lambda *_args, **_kwargs: object())

    first = connector_module.ASFConnector()
    second = connector_module.ASFConnector()

    assert first.log is first_logger
    assert second.log is second_logger
    assert not hasattr(connector_module, "LOG")
def test_constructor_passes_timeouts_to_ipc_protocol(monkeypatch):
    import ASFConnector as connector_module

    observed = {}

    class Protocol:
        def __init__(self, *_args, **kwargs):
            observed.update(kwargs)

    monkeypatch.setattr(connector_module, "IPCProtocolHandler", Protocol)

    connector_module.ASFConnector(
        "asf", "1242", password="password",
        connect_timeout=2.5, read_timeout=40,
    )

    assert observed["connect_timeout"] == 2.5
    assert observed["read_timeout"] == 40
