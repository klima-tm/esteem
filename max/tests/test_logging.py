from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from pymax.logging import (
    PYMAX_HANDLER_ATTR,
    PrettyFormatter,
    configure_logging,
    get_logger,
)


@pytest.fixture
def isolated_logging() -> Iterator[None]:
    root = logging.getLogger()
    pymax = logging.getLogger("pymax")

    root_handlers = list(root.handlers)
    root_level = root.level
    root_propagate = root.propagate
    pymax_handlers = list(pymax.handlers)
    pymax_level = pymax.level
    pymax_propagate = pymax.propagate

    root.handlers.clear()
    pymax.handlers.clear()
    pymax.propagate = True

    try:
        yield
    finally:
        root.handlers.clear()
        root.handlers.extend(root_handlers)
        root.setLevel(root_level)
        root.propagate = root_propagate

        pymax.handlers.clear()
        pymax.handlers.extend(pymax_handlers)
        pymax.setLevel(pymax_level)
        pymax.propagate = pymax_propagate


def test_configure_logging_installs_pretty_handler_by_default(
    isolated_logging: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.StringIO()
    monkeypatch.setattr(
        "pymax.logging._logging_already_configured",
        lambda logger: False,
    )

    configure_logging("DEBUG", stream=stream, use_colors=False)

    logger = logging.getLogger("pymax")
    assert logger.level == logging.DEBUG
    assert logger.propagate is False
    assert len(logger.handlers) == 1
    assert isinstance(logger.handlers[0].formatter, PrettyFormatter)
    assert getattr(logger.handlers[0], PYMAX_HANDLER_ATTR) is True

    get_logger("pymax.test").debug("hello")

    assert "DEBUG hello" in stream.getvalue()


def test_configure_logging_respects_existing_root_logging(
    isolated_logging: None,
) -> None:
    root_stream = io.StringIO()
    pymax_stream = io.StringIO()
    root = logging.getLogger()
    pymax = logging.getLogger("pymax")
    root_handler = logging.StreamHandler(root_stream)
    root_handler.setFormatter(logging.Formatter("ROOT:%(name)s:%(message)s"))
    root.addHandler(root_handler)
    root.setLevel(logging.DEBUG)
    pymax.addHandler(logging.NullHandler())
    pymax.propagate = False

    configure_logging("DEBUG", stream=pymax_stream, use_colors=False)

    assert pymax.handlers and isinstance(pymax.handlers[0], logging.NullHandler)
    assert len(pymax.handlers) == 1
    assert pymax.propagate is True

    get_logger("pymax.test").debug("hello")

    assert "ROOT:pymax.test:hello" in root_stream.getvalue()
    assert pymax_stream.getvalue() == ""


def test_configure_logging_respects_existing_pymax_handler(
    isolated_logging: None,
) -> None:
    custom_stream = io.StringIO()
    pymax_stream = io.StringIO()
    pymax = logging.getLogger("pymax")
    custom_handler = logging.StreamHandler(custom_stream)
    custom_handler.setFormatter(logging.Formatter("CUSTOM:%(message)s"))
    pymax.addHandler(custom_handler)
    pymax.propagate = False

    configure_logging("DEBUG", stream=pymax_stream, use_colors=False)

    assert pymax.handlers == [custom_handler]
    assert pymax.propagate is False

    get_logger("pymax.test").debug("hello")

    assert custom_stream.getvalue().strip() == "CUSTOM:hello"
    assert pymax_stream.getvalue() == ""


def test_configure_logging_force_replaces_existing_handlers(
    isolated_logging: None,
) -> None:
    root_stream = io.StringIO()
    custom_stream = io.StringIO()
    pymax_stream = io.StringIO()
    root = logging.getLogger()
    pymax = logging.getLogger("pymax")
    root.addHandler(logging.StreamHandler(root_stream))
    pymax.addHandler(logging.StreamHandler(custom_stream))

    configure_logging(
        "DEBUG",
        stream=pymax_stream,
        use_colors=False,
        force=True,
    )

    assert len(pymax.handlers) == 1
    assert getattr(pymax.handlers[0], PYMAX_HANDLER_ATTR) is True
    assert pymax.propagate is False

    get_logger("pymax.test").debug("hello")

    assert "DEBUG hello" in pymax_stream.getvalue()
    assert custom_stream.getvalue() == ""
    assert root_stream.getvalue() == ""


def test_configure_logging_replaces_own_pretty_handler(
    isolated_logging: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_stream = io.StringIO()
    second_stream = io.StringIO()
    monkeypatch.setattr(
        "pymax.logging._logging_already_configured",
        lambda logger: False,
    )

    configure_logging("INFO", stream=first_stream, use_colors=False)
    configure_logging("DEBUG", stream=second_stream, use_colors=False)

    logger = logging.getLogger("pymax")
    assert len(logger.handlers) == 1
    assert logger.handlers[0].level == logging.DEBUG

    get_logger("pymax.test").debug("hello")

    assert first_stream.getvalue() == ""
    assert "DEBUG hello" in second_stream.getvalue()
