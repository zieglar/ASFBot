import importlib
import logging

import ASFConnector
import IPCProtocol
import logger as logger_module


def fresh_logger():
    return importlib.reload(logger_module)


def test_connectors_can_be_constructed_before_explicit_logger_setup():
    log = fresh_logger()

    connector = ASFConnector.ASFConnector()
    protocol = IPCProtocol.IPCProtocolHandler("asf", "1242")

    assert connector.log.name == "ASFBot.ASFConnector"
    assert protocol.log.name == "ASFBot.IPCProtocol"
    assert log.get_logger().name == "ASFBot"


def test_repeated_setup_does_not_add_duplicate_stream_handlers():
    log = fresh_logger()
    name = "ASFBot.logger-idempotence-test"

    first = log.set_logger(name)
    second = log.set_logger(name)

    stream_handlers = [
        handler for handler in second.handlers
        if type(handler) is logging.StreamHandler
    ]
    assert second is first
    assert len(stream_handlers) == 1
    assert stream_handlers[0].formatter._fmt == log.DEFAULT_FORMATTER._fmt


def test_log_level_can_be_set_before_and_after_setup():
    log = fresh_logger()

    log.set_level("INFO")
    configured = log.set_logger("ASFBot.logger-level-test")

    assert configured.level == logging.INFO
    assert all(handler.level == logging.INFO for handler in configured.handlers)

    log.set_level("WARNING")

    assert configured.level == logging.WARNING
    assert all(handler.level == logging.WARNING for handler in configured.handlers)
