import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeBot:
    def __init__(self):
        self.routes, self.replies = [], []

    def message_handler(self, **route):
        def register(handler):
            self.routes.append((route, handler))
            return handler
        return register

    def reply_to(self, _message, text, **kwargs):
        self.replies.append((text, kwargs))


class RecordingConnector:
    def __init__(self, asf_info=None):
        self.calls = []
        self.asf_info = {"Success": True} if asf_info is None else asf_info

    def get_asf_info(self):
        self.calls.append(("get_asf_info", ()))
        return self.asf_info

    def get_bot_info(self, bot):
        self.calls.append(("get_bot_info", (bot,)))
        return "status <remote> & okay"

    def bot_redeem(self, bot, keys):
        self.calls.append(("bot_redeem", (bot, keys)))
        return "redeemed <remote> & okay"

    def send_command(self, command):
        self.calls.append(("send_command", (command,)))
        return "command <remote> & okay"


def message(text, user_id=123):
    return SimpleNamespace(from_user=SimpleNamespace(id=user_id), text=text)


def dispatch(fake_bot, incoming):
    """Approximate pyTelegramBotAPI's first-match handler ordering."""
    command = (incoming.text[1:].split(None, 1)[0].split("@", 1)[0].lower()
               if incoming.text.startswith(("/", "!")) else None)
    for route, handler in fake_bot.routes:
        if not route["func"](incoming):
            continue
        if "commands" in route and command not in route["commands"]:
            continue
        if "regexp" in route and not re.search(route["regexp"], incoming.text, re.IGNORECASE):
            continue
        if "content_types" in route and "text" not in route["content_types"]:
            continue
        handler(incoming)
        return


def dispatch_with_real_telebot_filters(telegram_bot, incoming):
    """Dispatch one message using pyTelegramBotAPI's actual filter behavior."""
    incoming.content_type = "text"
    for handler in telegram_bot.message_handlers:
        if telegram_bot._test_message_handler(handler, incoming):
            handler["function"](incoming)
            return


@pytest.mark.parametrize("sender, expected", [(123, True), (999, False)])
def test_authorization_uses_numeric_sender_id(sender, expected):
    from bot import is_allowed_user
    assert is_allowed_user(message("/ping", sender), frozenset({123})) is expected
    assert is_allowed_user(SimpleNamespace(from_user=None), frozenset({123})) is False


def test_all_routes_share_authorization_and_denied_messages_make_zero_calls():
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    predicates = [route["func"] for route, _ in bot.routes]
    assert predicates and all(predicate is predicates[0] for predicate in predicates)
    for text in ("/status", "/pause main", "/redeem main AAAAA-BBBBB-CCCCC",
                 "/help", "/ping", "/version", "AAAAA-BBBBB-CCCCC"):
        dispatch(bot, message(text, 999))
    assert connector.calls == []
    assert bot.replies == []


@pytest.mark.parametrize(("text", "method", "args"), [
    ("/status", "get_bot_info", ("ASF",)),
    ("/status main", "get_bot_info", ("main",)),
    ("/pause main", "send_command", ("pause main",)),
    ("/resume main", "send_command", ("resume main",)),
    ("/start main", "send_command", ("start main",)),
    ("/stop main", "send_command", ("stop main",)),
])
def test_supported_commands_call_expected_connector_method(text, method, args):
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message(text))
    assert connector.calls == [(method, args)]
    assert "&lt;remote&gt; &amp; okay" in bot.replies[0][0]
    assert bot.replies[0][1]["parse_mode"] == "HTML"


@pytest.mark.parametrize("text", ["/pause", "/resume", "/start", "/stop", "/status one two"])
def test_malformed_supported_commands_show_usage_without_falling_through_to_raw(text):
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message(text))
    assert connector.calls == []
    assert "Usage" in bot.replies[0][0]


def test_redeem_requires_bot_and_valid_keys_and_deduplicates():
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message("/redeem main aaaaa-bbbbb-ccccc AAAAA-BBBBB-CCCCC ddddd-eeeee-fffff"))
    assert connector.calls == [("bot_redeem", ("main", {"AAAAA-BBBBB-CCCCC", "DDDDD-EEEEE-FFFFF"}))]
    dispatch(bot, message("/redeem main not-a-key"))
    assert len(connector.calls) == 1
    assert "Usage" in bot.replies[-1][0]


def test_help_documents_all_supported_syntax_without_connector_call():
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message("/help"))
    help_text = bot.replies[0][0]
    for syntax in ("/status [bot]", "/pause &lt;bot&gt;", "/resume &lt;bot&gt;",
                   "/start &lt;bot&gt;", "/stop &lt;bot&gt;", "/redeem &lt;bot&gt; &lt;keys&gt;", "/ping"):
        assert syntax in help_text
    assert connector.calls == []


def test_help_rejects_extra_arguments_without_connector_call():
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message("/help extra"))
    assert "Usage" in bot.replies[0][0]
    assert connector.calls == []


def test_redeem_rejects_more_than_twenty_keys_without_connector_call():
    from bot import register_handlers
    keys = [f"A{i:04d}-BBBBB-CCCCC" for i in range(21)]
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message("/redeem main " + " ".join(keys)))
    assert connector.calls == []
    assert "20" in bot.replies[0][0]


def test_auto_redeem_rejects_more_than_twenty_keys_without_connector_call():
    from bot import register_handlers
    keys = [f"A{i:04d}-BBBBB-CCCCC" for i in range(21)]
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message(" ".join(keys)))
    assert connector.calls == []
    assert "20" in bot.replies[0][0]


def test_key_limit_counts_occurrences_before_deduplication():
    from bot import register_handlers
    repeated = " ".join(["AAAAA-BBBBB-CCCCC"] * 21)
    for text in ("/redeem main " + repeated, repeated):
        bot, connector = FakeBot(), RecordingConnector()
        register_handlers(bot, connector, frozenset({123}))
        dispatch(bot, message(text))
        assert connector.calls == []
        assert "20" in bot.replies[0][0]


def test_auto_redeem_rejects_oversized_text_without_scanning_or_connector_call():
    from bot import MAX_TEXT_SCAN_LENGTH, register_handlers

    suffix_keys = " ".join(f"A{i:04d}-BBBBB-CCCCC" for i in range(21))
    oversized = "AAAAA-BBBBB-CCCCC " + ("x" * MAX_TEXT_SCAN_LENGTH) + suffix_keys
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message(oversized))

    assert connector.calls == []
    assert "too long" in bot.replies[0][0].lower()


@pytest.mark.parametrize(("asf_info", "expected"), [
    ({"Success": True}, "ASF IPC: reachable"),
    ({"Success": False, "Message": "ASF IPC request timed out."}, "ASF IPC: unreachable"),
    ({"Success": False, "Message": "Unable to connect to ASF IPC."}, "ASF IPC: unreachable"),
    ({"Success": False, "Message": "ASF IPC returned HTTP 401."}, "ASF IPC: unreachable"),
])
def test_ping_reports_bot_alive_and_safe_asf_reachability(asf_info, expected):
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector(asf_info)
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message("/ping"))
    assert "Telegram bot: alive" in bot.replies[0][0]
    assert expected in bot.replies[0][0]
    assert "timed out" not in bot.replies[0][0]
    assert "401" not in bot.replies[0][0]


def test_authorized_unknown_slash_command_is_forwarded_but_malformed_prefix_is_not():
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message("/version ASF"))
    dispatch(bot, message("/ status ASF"))
    assert connector.calls == [("send_command", ("version ASF",))]


def test_handlers_are_registered_specific_first_raw_second_and_plain_text_last():
    from bot import register_handlers
    bot = FakeBot()
    register_handlers(bot, RecordingConnector(), frozenset({123}))
    kinds = ["reserved" if route.get("regexp", "").startswith("^[/!](?:")
             else "regexp" if "regexp" in route else "text"
             for route, _ in bot.routes]
    assert kinds[-2:] == ["regexp", "text"]
    assert all(kind == "reserved" for kind in kinds[:-2])


@pytest.mark.parametrize(("text", "expected_call"), [
    ("/STATUS main", ("get_bot_info", ("main",))),
    ("!status main", ("get_bot_info", ("main",))),
    ("/PAUSE main", ("send_command", ("pause main",))),
    ("!resume main", ("send_command", ("resume main",))),
    ("/START main", ("send_command", ("start main",))),
    ("!stop main", ("send_command", ("stop main",))),
])
def test_reserved_commands_have_uppercase_slash_and_bang_parity_with_real_filters(text, expected_call):
    import telebot
    from bot import register_handlers
    telegram_bot = telebot.TeleBot("123:ABC")
    telegram_bot.reply_to = lambda *_args, **_kwargs: None
    connector = RecordingConnector()
    register_handlers(telegram_bot, connector, frozenset({123}))
    dispatch_with_real_telebot_filters(telegram_bot, message(text))
    assert connector.calls == [expected_call]


@pytest.mark.parametrize("text", ["/PAUSE", "!resume", "/START too many", "!stop"])
def test_malformed_reserved_variants_never_reach_raw_with_real_filters(text):
    import telebot
    from bot import register_handlers
    telegram_bot = telebot.TeleBot("123:ABC")
    replies, connector = [], RecordingConnector()
    telegram_bot.reply_to = lambda _message, reply, **_kwargs: replies.append(reply)
    register_handlers(telegram_bot, connector, frozenset({123}))
    dispatch_with_real_telebot_filters(telegram_bot, message(text))
    assert connector.calls == []
    assert replies and "Usage" in replies[0]


@pytest.mark.parametrize(("text", "expected_call"), [
    ("/stop main", ("send_command", ("stop main",))),
    ("/STOP@MyAsfBot main", ("send_command", ("stop main",))),
    ("!stop@myasfbot main", ("send_command", ("stop main",))),
    ("/redeem main AAAAA-BBBBB-CCCCC",
     ("bot_redeem", ("main", {"AAAAA-BBBBB-CCCCC"}))),
    ("/REDEEM@MYASFBOT main AAAAA-BBBBB-CCCCC",
     ("bot_redeem", ("main", {"AAAAA-BBBBB-CCCCC"}))),
    ("/version ASF", ("send_command", ("version ASF",))),
    ("/version@MyAsfBot ASF", ("send_command", ("version ASF",))),
    ("!version@myasfbot ASF", ("send_command", ("version ASF",))),
])
def test_commands_without_suffix_or_addressed_to_this_bot_execute_with_real_filters(
        text, expected_call):
    import telebot
    from bot import register_handlers
    telegram_bot = telebot.TeleBot("123:ABC")
    telegram_bot.reply_to = lambda *_args, **_kwargs: None
    connector = RecordingConnector()
    register_handlers(telegram_bot, connector, frozenset({123}), "MyAsfBot")
    dispatch_with_real_telebot_filters(telegram_bot, message(text))
    assert connector.calls == [expected_call]


@pytest.mark.parametrize("text", [
    "/stop@OtherBot main",
    "!STOP@otherbot main",
    "/redeem@OtherBot main AAAAA-BBBBB-CCCCC",
    "!REDEEM@otherbot main AAAAA-BBBBB-CCCCC",
    "/version@OtherBot ASF",
    "!version@otherbot ASF",
])
def test_commands_addressed_to_another_bot_are_ignored_with_real_filters(text):
    import telebot
    from bot import register_handlers
    telegram_bot = telebot.TeleBot("123:ABC")
    replies, connector = [], RecordingConnector()
    telegram_bot.reply_to = lambda _message, reply, **_kwargs: replies.append(reply)
    register_handlers(telegram_bot, connector, frozenset({123}), "MyAsfBot")
    dispatch_with_real_telebot_filters(telegram_bot, message(text))
    assert connector.calls == []
    assert replies == []


def test_bang_redeem_limit_cannot_fall_through_to_raw_with_real_filters():
    import telebot
    from bot import register_handlers
    telegram_bot = telebot.TeleBot("123:ABC")
    replies, connector = [], RecordingConnector()
    telegram_bot.reply_to = lambda _message, reply, **_kwargs: replies.append(reply)
    register_handlers(telegram_bot, connector, frozenset({123}))
    keys = " ".join(f"A{i:04d}-BBBBB-CCCCC" for i in range(21))
    dispatch_with_real_telebot_filters(telegram_bot, message("!REDEEM main " + keys))
    assert connector.calls == []
    assert replies and "20 key occurrences" in replies[0]


def test_plain_text_recognizes_full_token_keys_case_insensitively_and_deduplicates():
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message("Keys: aaaaa-bbbbb-ccccc, DDDDD-EEEEE-FFFFF; AAAAA-BBBBB-CCCCC"))
    assert connector.calls == [("bot_redeem", ("ASF", {"AAAAA-BBBBB-CCCCC", "DDDDD-EEEEE-FFFFF"}))]


@pytest.mark.parametrize("text", ["xAAAAA-BBBBB-CCCCC", "AAAAA-BBBBB-CCCCCx",
                                   "AAAAA_BBBBB-CCCCC-DDDDD", "AAAA-BBBBB-CCCCC",
                                   "AAAAAA-BBBBB-CCCCC"])
def test_plain_text_rejects_keys_embedded_in_larger_tokens(text):
    from bot import register_handlers
    bot, connector = FakeBot(), RecordingConnector()
    register_handlers(bot, connector, frozenset({123}))
    dispatch(bot, message(text))
    assert connector.calls == []


def test_remote_output_is_html_escaped_exactly_once():
    from bot import register_handlers
    bot = FakeBot()
    register_handlers(bot, RecordingConnector(), frozenset({123}))
    dispatch(bot, message("/status main"))
    text, _ = bot.replies[0]
    assert "&lt;remote&gt; &amp; okay" in text
    assert "&amp;lt;" not in text


def test_remote_output_is_safely_truncated_within_telegram_limit():
    from bot import register_handlers

    class LongResultConnector(RecordingConnector):
        def get_bot_info(self, bot):
            self.calls.append(("get_bot_info", (bot,)))
            return "<&>" * 2000

    bot = FakeBot()
    register_handlers(bot, LongResultConnector(), frozenset({123}))
    dispatch(bot, message("/status main"))

    text, kwargs = bot.replies[0]
    assert len(text) <= 4096
    assert text.endswith("\n… [truncated]</code>")
    assert kwargs["parse_mode"] == "HTML"
    assert text.count("&lt;") == text.count("&gt;")


@pytest.mark.parametrize("text", [
    "/status main", "/pause main", "/redeem main AAAAA-BBBBB-CCCCC",
    "/version ASF", "AAAAA-BBBBB-CCCCC",
])
def test_connector_exceptions_are_presented_safely_for_every_connector_route(text, caplog):
    from bot import register_handlers

    secret = "private exception details <secret>"

    class FailingConnector:
        def __getattr__(self, _name):
            def fail(*_args, **_kwargs):
                raise RuntimeError(secret)
            return fail

    bot = FakeBot()
    register_handlers(bot, FailingConnector(), frozenset({123}))
    with caplog.at_level(logging.ERROR):
        dispatch(bot, message(text))
    assert bot.replies
    assert secret not in bot.replies[0][0]
    assert secret not in caplog.text


def test_both_telegram_reply_failures_are_contained(caplog):
    from bot import register_handlers

    class AlwaysFailingBot(FakeBot):
        def reply_to(self, *_args, **_kwargs):
            raise RuntimeError("telegram secret response")

    bot = AlwaysFailingBot()
    register_handlers(bot, RecordingConnector(), frozenset({123}))
    with caplog.at_level(logging.ERROR):
        dispatch(bot, message("/help"))
    assert "telegram secret response" not in caplog.text


def test_startup_logs_do_not_expose_credentials_from_exceptions(monkeypatch, caplog):
    import bot as bot_module
    token, password = "secret-telegram-token", "secret-ipc-password"
    config = bot_module.Config("DEBUG", "asf", "1242", password, token, None, frozenset({123}))

    class FailingConnector:
        def __init__(self, *_args, **_kwargs): pass
        def get_asf_info(self): raise RuntimeError(f"request failed with {password}")

    class TelegramBot(FakeBot):
        def __init__(self, supplied_token):
            super().__init__()
            assert supplied_token == token
        def get_me(self): return SimpleNamespace(username="MyAsfBot")
        def infinity_polling(self): raise RuntimeError(f"polling failed for {token}")

    monkeypatch.setattr(bot_module, "load_config", lambda _argv: config)
    monkeypatch.setattr(bot_module, "ASFConnector", FailingConnector)
    monkeypatch.setattr(bot_module.telebot, "TeleBot", TelegramBot)
    with caplog.at_level(logging.DEBUG):
        assert bot_module.main([]) == 1
    assert token not in caplog.text
    assert password not in caplog.text


def test_startup_gets_bot_username_once_and_injects_it_into_handlers(monkeypatch):
    import bot as bot_module
    config = bot_module.Config("INFO", "asf", "1242", None, "123:ABC", None,
                               frozenset({123}))
    observed = {}

    class Connector:
        def __init__(self, *_args, **_kwargs): pass
        def get_asf_info(self): return {"Success": True}

    class TelegramBot(FakeBot):
        get_me_calls = 0
        def __init__(self, _token):
            super().__init__()
            observed["telegram_bot"] = self
        def get_me(self):
            self.get_me_calls += 1
            return SimpleNamespace(username="MyAsfBot")
        def infinity_polling(self): pass

    def register(_bot, _connector, _allowed_ids, bot_username):
        observed["username"] = bot_username

    monkeypatch.setattr(bot_module, "load_config", lambda _argv: config)
    monkeypatch.setattr(bot_module, "ASFConnector", Connector)
    monkeypatch.setattr(bot_module.telebot, "TeleBot", TelegramBot)
    monkeypatch.setattr(bot_module, "register_handlers", register)

    assert bot_module.main([]) == 0
    assert observed["username"] == "MyAsfBot"
    assert observed["telegram_bot"].get_me_calls == 1


@pytest.mark.parametrize("get_me_result", [RuntimeError("token detail"), SimpleNamespace(username=None)])
def test_startup_fails_closed_when_bot_identity_cannot_be_obtained(
        monkeypatch, caplog, get_me_result):
    import bot as bot_module
    config = bot_module.Config("INFO", "asf", "1242", None, "secret-token", None,
                               frozenset({123}))
    events = []

    class Connector:
        def __init__(self, *_args, **_kwargs): pass
        def get_asf_info(self):
            events.append("asf")
            return {"Success": True}

    class TelegramBot(FakeBot):
        def __init__(self, _token): super().__init__()
        def get_me(self):
            if isinstance(get_me_result, Exception):
                raise get_me_result
            return get_me_result
        def infinity_polling(self): events.append("poll")

    monkeypatch.setattr(bot_module, "load_config", lambda _argv: config)
    monkeypatch.setattr(bot_module, "ASFConnector", Connector)
    monkeypatch.setattr(bot_module.telebot, "TeleBot", TelegramBot)
    with caplog.at_level(logging.ERROR):
        assert bot_module.main([]) == 1
    assert events == []
    assert "secret-token" not in caplog.text
    assert "token detail" not in caplog.text
    assert "identity" in caplog.text.lower()


def test_importing_bot_has_no_runtime_side_effects():
    environment = os.environ.copy()
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_ID", "TELEGRAM_USER_ALIAS"):
        environment.pop(name, None)
    result = subprocess.run([sys.executable, "-c", "import bot"], cwd=PROJECT_ROOT,
                            env=environment, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
