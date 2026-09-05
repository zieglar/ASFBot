import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def parse_allowed_user_ids(raw_value):
    bot_module = importlib.import_module("bot")
    return bot_module.parse_allowed_user_ids(raw_value)


def test_parses_one_allowed_user_id():
    assert parse_allowed_user_ids("123456789") == frozenset({123456789})


def test_parses_multiple_comma_separated_ids_with_whitespace():
    assert parse_allowed_user_ids("123, 456,789") == frozenset({123, 456, 789})


@pytest.mark.parametrize("raw_value", ["", " ", "123,,456", "username", "0", "-1"])
def test_rejects_empty_non_numeric_or_non_positive_ids(raw_value):
    with pytest.raises(ValueError, match="TELEGRAM_ALLOWED_USER_ID"):
        parse_allowed_user_ids(raw_value)


def test_configuration_reads_current_environment_names():
    bot_module = importlib.import_module("bot")

    config = bot_module.load_config(
        [],
        {
            "TELEGRAM_BOT_TOKEN": " token ",
            "TELEGRAM_ALLOWED_USER_ID": "123, 456",
            "TELEGRAM_PROXY": " http://proxy.example:8080 ",
            "ASF_IPC_HOST": " asf ",
            "ASF_IPC_PORT": " 1242 ",
            "ASF_IPC_PASSWORD": " password ",
            "ASF_IPC_CONNECT_TIMEOUT": "2.5",
            "ASF_IPC_READ_TIMEOUT": "30",
        },
    )

    assert config.token == "token"
    assert config.allowed_user_ids == frozenset({123, 456})
    assert config.proxy == "http://proxy.example:8080"
    assert config.host == "asf"
    assert config.port == "1242"
    assert config.password == "password"
    assert config.connect_timeout == 2.5
    assert config.read_timeout == 30.0


def test_environment_values_override_conflicting_command_line_values():
    bot_module = importlib.import_module("bot")

    config = bot_module.load_config(
        [
            "--token", "cli-token",
            "--allowed-user-id", "999",
            "--proxy", "http://cli-proxy:8080",
            "--host", "cli-asf",
            "--port", "9999",
            "--password", "cli-password",
            "--connect-timeout", "1",
            "--read-timeout", "2",
        ],
        {
            "TELEGRAM_BOT_TOKEN": "env-token",
            "TELEGRAM_ALLOWED_USER_ID": "123,456",
            "TELEGRAM_PROXY": "http://env-proxy:8080",
            "ASF_IPC_HOST": "env-asf",
            "ASF_IPC_PORT": "1242",
            "ASF_IPC_PASSWORD": "env-password",
            "ASF_IPC_CONNECT_TIMEOUT": "4.5",
            "ASF_IPC_READ_TIMEOUT": "25",
        },
    )

    assert config.token == "env-token"
    assert config.allowed_user_ids == frozenset({123, 456})
    assert config.proxy == "http://env-proxy:8080"
    assert config.host == "env-asf"
    assert config.port == "1242"
    assert config.password == "env-password"
    assert config.connect_timeout == 4.5
    assert config.read_timeout == 25.0


def test_timeout_defaults_match_transport_defaults():
    bot_module = importlib.import_module("bot")

    config = bot_module.load_config(
        ["--token", "token", "--allowed-user-id", "123"],
        {},
    )

    assert config.connect_timeout == 3.05
    assert config.read_timeout == 15.0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ASF_IPC_CONNECT_TIMEOUT", "0"),
        ("ASF_IPC_CONNECT_TIMEOUT", "-1"),
        ("ASF_IPC_CONNECT_TIMEOUT", "nan"),
        ("ASF_IPC_READ_TIMEOUT", "inf"),
        ("ASF_IPC_READ_TIMEOUT", "soon"),
    ],
)
def test_rejects_non_finite_non_positive_or_non_numeric_timeouts(name, value):
    bot_module = importlib.import_module("bot")

    with pytest.raises(ValueError, match=name):
        bot_module.load_config(
            ["--token", "token", "--allowed-user-id", "123"],
            {name: value},
        )


def test_main_passes_configured_timeouts_to_connector(monkeypatch):
    bot_module = importlib.import_module("bot")
    observed = {}
    config = bot_module.Config(
        "INFO", "asf", "1242", "password", "token", None,
        frozenset({123}), 2.5, 40.0,
    )

    class Connector:
        def __init__(self, *_args, **kwargs):
            observed.update(kwargs)

        def get_asf_info(self):
            return {"Success": True}

    class TelegramBot:
        def __init__(self, _token):
            pass

        def message_handler(self, **_kwargs):
            return lambda handler: handler

        def get_me(self):
            return SimpleNamespace(username="MyAsfBot")

        def infinity_polling(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(bot_module, "load_config", lambda _argv: config)
    monkeypatch.setattr(bot_module, "ASFConnector", Connector)
    monkeypatch.setattr(bot_module.telebot, "TeleBot", TelegramBot)

    assert bot_module.main([]) == 0
    assert observed["password"] == "password"
    assert observed["connect_timeout"] == 2.5
    assert observed["read_timeout"] == 40.0


def test_command_line_allowed_user_id_is_supported():
    bot_module = importlib.import_module("bot")

    config = bot_module.load_config(
        ["--token", "token", "--allowed-user-id", "123,456"],
        {},
    )

    assert config.allowed_user_ids == frozenset({123, 456})


def test_old_alias_option_is_not_accepted():
    bot_module = importlib.import_module("bot")

    with pytest.raises(SystemExit):
        bot_module.load_config(["--token", "token", "--alias", "owner"], {})
