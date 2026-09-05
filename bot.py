#!/usr/bin/python3
"""Telegram frontend for ArchiSteamFarm with side-effect-free imports."""

import argparse
from dataclasses import dataclass
from html import escape
import math
import os
import re
from typing import Mapping, Sequence

import telebot
from telebot import apihelper

from ASFConnector import ASFConnector
import logger


_REGEX_CDKEY = re.compile(
    r"(?<![A-Z0-9_-])[A-Z0-9]{5}(?:-[A-Z0-9]{5}){2}(?![A-Z0-9_-])",
    re.IGNORECASE,
)
_REGEX_COMMAND_RAW = r"^[/!][A-Za-z][A-Za-z0-9_]*(?:@\w+)?(?:\s+\S(?:.*\S)?)?\s*$"
_ENV_TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
_ENV_TELEGRAM_ALLOWED_USER_ID = "TELEGRAM_ALLOWED_USER_ID"
_ENV_TELEGRAM_PROXY = "TELEGRAM_PROXY"
_ENV_ASF_IPC_HOST = "ASF_IPC_HOST"
_ENV_ASF_IPC_PORT = "ASF_IPC_PORT"
_ENV_ASF_IPC_PASSWORD = "ASF_IPC_PASSWORD"
_ENV_ASF_IPC_CONNECT_TIMEOUT = "ASF_IPC_CONNECT_TIMEOUT"
_ENV_ASF_IPC_READ_TIMEOUT = "ASF_IPC_READ_TIMEOUT"
LOG = logger.set_logger("ASFBot")
MAX_KEYS_PER_REQUEST = 20
MAX_TEXT_SCAN_LENGTH = 4096
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
_TRUNCATION_SUFFIX = "\n… [truncated]"


@dataclass(frozen=True)
class Config:
    verbosity: str
    host: str
    port: str
    password: str | None
    token: str
    proxy: str | None
    allowed_user_ids: frozenset[int]
    connect_timeout: float = 3.05
    read_timeout: float = 15.0


def parse_positive_timeout(raw_value, setting_name: str) -> float:
    """Parse a finite, positive timeout without accepting booleans or NaN."""
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{setting_name} must be a finite positive number") from error
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{setting_name} must be a finite positive number")
    return value


def parse_allowed_user_ids(raw_value: str) -> frozenset[int]:
    """Parse a comma-separated allowlist of positive Telegram user IDs."""
    parts = raw_value.split(",") if raw_value is not None else []
    try:
        values = [int(part.strip()) for part in parts if part.strip()]
    except ValueError as error:
        raise ValueError(
            "TELEGRAM_ALLOWED_USER_ID must contain comma-separated positive integers"
        ) from error
    if len(values) != len(parts) or not values or any(value <= 0 for value in values):
        raise ValueError(
            "TELEGRAM_ALLOWED_USER_ID must contain comma-separated positive integers"
        )
    return frozenset(values)


def is_allowed_user(message, allowed_user_ids: frozenset[int]) -> bool:
    """Return whether a message has a sender in the immutable ID allowlist."""
    sender = getattr(message, "from_user", None)
    return sender is not None and getattr(sender, "id", None) in allowed_user_ids


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbosity", choices=["CRITICAL", "ERROR", "WARN", "INFO", "DEBUG"], default="INFO")
    parser.add_argument("--host", default=None, help="ASF IPC host. Default: 127.0.0.1")
    parser.add_argument("--port", default=None, help="ASF IPC port. Default: 1242")
    parser.add_argument("--password", default=None, help="ASF IPC password")
    parser.add_argument("--token", default=None, help="Telegram API token given by @botfather")
    parser.add_argument("--proxy", default=None, help="Telegram proxy in <protocol>://<host>:<port> format")
    parser.add_argument("--allowed-user-id", default=None, help="Comma-separated numeric Telegram user IDs allowed to use the bot")
    parser.add_argument("--connect-timeout", default="3.05", help="ASF IPC connection timeout in seconds. Default: 3.05")
    parser.add_argument("--read-timeout", default="15", help="ASF IPC read timeout in seconds. Default: 15")
    return parser


def load_config(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> Config:
    """Load configuration with environment variables overriding CLI values."""
    environment = os.environ if environ is None else environ
    args = build_argument_parser().parse_args(argv)
    token = environment.get(_ENV_TELEGRAM_BOT_TOKEN, args.token)
    allowed_user_id = environment.get(_ENV_TELEGRAM_ALLOWED_USER_ID, args.allowed_user_id)
    if not token or not token.strip():
        raise ValueError("Telegram bot token is required via --token or TELEGRAM_BOT_TOKEN")
    if allowed_user_id is None:
        raise ValueError("Allowed Telegram user IDs are required via --allowed-user-id or TELEGRAM_ALLOWED_USER_ID")
    host = environment.get(_ENV_ASF_IPC_HOST, args.host or "127.0.0.1").strip()
    port = environment.get(_ENV_ASF_IPC_PORT, args.port or "1242").strip()
    password = environment.get(_ENV_ASF_IPC_PASSWORD, args.password)
    proxy = environment.get(_ENV_TELEGRAM_PROXY, args.proxy)
    connect_timeout = parse_positive_timeout(
        environment.get(_ENV_ASF_IPC_CONNECT_TIMEOUT, args.connect_timeout),
        _ENV_ASF_IPC_CONNECT_TIMEOUT,
    )
    read_timeout = parse_positive_timeout(
        environment.get(_ENV_ASF_IPC_READ_TIMEOUT, args.read_timeout),
        _ENV_ASF_IPC_READ_TIMEOUT,
    )
    return Config(
        verbosity=args.verbosity,
        host=host,
        port=port,
        password=password.strip() if password else None,
        token=token.strip(),
        proxy=proxy.strip() if proxy else None,
        allowed_user_ids=parse_allowed_user_ids(allowed_user_id),
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
    )


def register_handlers(
        bot,
        asf_connector,
        allowed_user_ids: frozenset[int],
        bot_username: str | None = None,
) -> None:
    """Register specific commands before raw and plain-text fallbacks."""
    def authorized(message):
        return (is_allowed_user(message, allowed_user_ids)
                and _is_addressed_to_this_bot(message, bot_username))

    def reply_to(message, text, **kwargs):
        try:
            bot.reply_to(message, text, parse_mode="HTML", **kwargs)
        except Exception:
            LOG.error("Telegram reply failed")
            try:
                bot.reply_to(message, "There was a Telegram error sending the message. Check the bot log for more details.")
            except Exception:
                LOG.error("Telegram fallback reply failed")

    def reply_result(message, result):
        reply_to(message, _format_code_reply(str(result)))

    def parts(message):
        return (getattr(message, "text", "") or "").strip().split()

    @bot.message_handler(func=authorized, regexp=_reserved_command_pattern("help"))
    def help_command(message):
        if len(parts(message)) != 1:
            reply_to(message, "Usage: <code>/help</code>")
            return
        reply_to(message, (
            "<b>ASFBot commands</b>\n"
            "/status [bot]\n"
            "/pause &lt;bot&gt;\n"
            "/resume &lt;bot&gt;\n"
            "/start &lt;bot&gt;\n"
            "/stop &lt;bot&gt;\n"
            "/redeem &lt;bot&gt; &lt;keys&gt; (maximum 20 keys)\n"
            "/ping\n\n"
            "You can also send complete Steam keys, or an ASF command prefixed with / or !."
        ))

    @bot.message_handler(func=authorized, regexp=_reserved_command_pattern("ping"))
    def ping_command(message):
        if len(parts(message)) != 1:
            reply_to(message, "Usage: <code>/ping</code>")
            return
        try:
            response = asf_connector.get_asf_info()
            reachable = isinstance(response, dict) and response.get("Success") is True
        except Exception:
            LOG.error("Unexpected ASF ping error")
            reachable = False
        state = "reachable" if reachable else "unreachable"
        reply_to(message, "Telegram bot: alive\nASF IPC: " + state)

    @bot.message_handler(func=authorized, regexp=_reserved_command_pattern("status"))
    def status_command(message):
        arguments = parts(message)
        if len(arguments) not in (1, 2):
            reply_to(message, "Usage: <code>/status [bot]</code>")
            return
        try:
            reply_result(message, asf_connector.get_bot_info(arguments[1] if len(arguments) == 2 else "ASF"))
        except Exception:
            LOG.error("Unexpected status error")
            reply_to(message, "Unable to query ASF IPC.")

    @bot.message_handler(func=authorized, regexp=_reserved_command_pattern("pause", "resume", "start", "stop"))
    def bot_action_command(message):
        arguments = parts(message)
        command = arguments[0][1:].split("@", 1)[0].lower() if arguments else ""
        if len(arguments) != 2:
            reply_to(message, f"Usage: <code>/{command} &lt;bot&gt;</code>")
            return
        try:
            reply_result(message, asf_connector.send_command(f"{command} {arguments[1]}"))
        except Exception:
            LOG.error("Unexpected ASF action error")
            reply_to(message, "Unable to send command to ASF IPC.")

    @bot.message_handler(func=authorized, regexp=_reserved_command_pattern("redeem"))
    def redeem_command(message):
        arguments = parts(message)
        keys = _canonical_keys(arguments[2:]) if len(arguments) >= 3 else []
        if (len(arguments) < 3
                or not all(_REGEX_CDKEY.fullmatch(value) for value in arguments[2:])):
            reply_to(message, "Usage: <code>/redeem &lt;bot&gt; &lt;keys&gt;</code>")
            return
        if len(arguments[2:]) > MAX_KEYS_PER_REQUEST:
            reply_to(message, "A maximum of 20 key occurrences is allowed per request.")
            return
        try:
            reply_result(message, asf_connector.bot_redeem(arguments[1], set(keys)))
        except Exception:
            LOG.error("Unexpected ASF redeem error")
            reply_to(message, "Unable to redeem keys through ASF IPC.")

    @bot.message_handler(func=authorized, regexp=_REGEX_COMMAND_RAW)
    def command_handler(message):
        raw = message.text.strip()[1:]
        command, separator, remainder = raw.partition(" ")
        command = command.split("@", 1)[0]
        ipc_command = command + (separator + remainder.strip() if separator else "")
        try:
            reply_result(message, asf_connector.send_command(ipc_command))
        except Exception:
            LOG.error("Unexpected raw ASF command error")
            reply_to(message, "Unable to send command to ASF IPC.")

    @bot.message_handler(func=authorized, content_types=["text"])
    def check_for_cdkeys(message):
        text = message.text or ""
        if len(text) > MAX_TEXT_SCAN_LENGTH:
            reply_to(message, "Message is too long to scan safely for Steam keys.")
            return
        matches = _REGEX_CDKEY.findall(text)
        cdkeys = _canonical_keys(matches)
        if cdkeys:
            if len(matches) > MAX_KEYS_PER_REQUEST:
                reply_to(message, "A maximum of 20 key occurrences is allowed per request.")
                return
            try:
                reply_result(message, asf_connector.bot_redeem("ASF", set(cdkeys)))
            except Exception:
                LOG.error("Unexpected automatic redeem error")
                reply_to(message, "Unable to redeem keys through ASF IPC.")


def _canonical_keys(values):
    """Return valid uppercase keys once, retaining their first-seen order."""
    keys = []
    seen = set()
    for value in values:
        if not _REGEX_CDKEY.fullmatch(value):
            return []
        canonical = value.upper()
        if canonical not in seen:
            seen.add(canonical)
            keys.append(canonical)
    return keys


def _reserved_command_pattern(*names: str) -> str:
    """Match a reserved command for both supported prefixes and any casing."""
    alternatives = "|".join(re.escape(name) for name in names)
    return rf"^[/!](?:(?i:{alternatives}))(?:@\w+)?(?:\s|$)"


def _is_addressed_to_this_bot(message, bot_username: str | None) -> bool:
    """Accept unsuffixed commands and commands explicitly addressed to this bot."""
    text = (getattr(message, "text", "") or "").lstrip()
    if not text.startswith(("/", "!")):
        return True
    command_token = text.split(None, 1)[0]
    _command, separator, addressed_username = command_token.partition("@")
    if not separator:
        return True
    return bool(bot_username) and addressed_username.casefold() == bot_username.casefold()


def _format_code_reply(value: str) -> str:
    """Build one valid HTML reply without exceeding Telegram's message limit."""
    prefix, suffix = "<code>", "</code>"
    escaped = replace_html_entities(value)
    if len(prefix) + len(escaped) + len(suffix) <= MAX_TELEGRAM_MESSAGE_LENGTH:
        return prefix + escaped + suffix

    budget = MAX_TELEGRAM_MESSAGE_LENGTH - len(prefix) - len(_TRUNCATION_SUFFIX) - len(suffix)
    fragments = []
    used = 0
    for character in value:
        fragment = replace_html_entities(character)
        if used + len(fragment) > budget:
            break
        fragments.append(fragment)
        used += len(fragment)
    return prefix + "".join(fragments) + _TRUNCATION_SUFFIX + suffix


def replace_html_entities(message: str) -> str:
    return escape(message, quote=False)


def configure_proxy(proxy: str | None) -> None:
    if not proxy:
        return
    if "://" not in proxy:
        LOG.error("Invalid Telegram proxy provided; skipping it")
        return
    protocol, url = proxy.split("://", 1)
    apihelper.proxy = {protocol: url}
    LOG.info("Using %s proxy to connect to Telegram", protocol)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config = load_config(argv)
    except ValueError as error:
        LOG.critical("%s", error)
        return 2
    logger.set_level(config.verbosity)
    LOG.info("Starting ASFBot")
    LOG.debug("Telegram proxy configured: %s", bool(config.proxy))
    LOG.debug("Allowed Telegram user count: %s", len(config.allowed_user_ids))
    LOG.debug("ASF IPC host: %s", config.host)
    LOG.debug("ASF IPC port: %s", config.port)
    LOG.debug("ASF IPC connect timeout: %s seconds", config.connect_timeout)
    LOG.debug("ASF IPC read timeout: %s seconds", config.read_timeout)
    configure_proxy(config.proxy)
    asf_connector = ASFConnector(
        config.host,
        config.port,
        password=config.password,
        connect_timeout=config.connect_timeout,
        read_timeout=config.read_timeout,
    )
    telegram_bot = telebot.TeleBot(config.token)
    try:
        identity = telegram_bot.get_me()
        bot_username = getattr(identity, "username", None)
        if not isinstance(bot_username, str) or not bot_username:
            raise ValueError("missing Telegram bot username")
    except Exception:
        LOG.error("Could not verify Telegram bot identity; refusing to start")
        return 1
    register_handlers(
        telegram_bot,
        asf_connector,
        config.allowed_user_ids,
        bot_username,
    )
    try:
        asf_info = asf_connector.get_asf_info()
        LOG.info("ASF instance replied successfully: %s", bool(asf_info.get("Success")))
    except Exception:
        LOG.error("Could not communicate with ASF at %s:%s", config.host, config.port)
    try:
        LOG.debug("Telegram polling started")
        telegram_bot.infinity_polling()
    except KeyboardInterrupt:
        LOG.info("Exiting")
    except Exception:
        LOG.error("Telegram polling failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
