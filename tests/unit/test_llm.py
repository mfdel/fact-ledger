"""``fact_ledger.llm.complete``.

The suite runs without a provider key, so every test here either fails before any network call or
uses LiteLLM's own ``mock_response``. Neither test needs a live model. Each test clears the
``get_settings`` cache before reading ``FACT_LEDGER_LLM_MODEL``, the same way the
``cli_env`` fixture does; no teardown is needed, because every other test that reads
settings clears the cache itself before it does.
"""

import functools
from pathlib import Path

import pytest
from pydantic import BaseModel

from fact_ledger import llm
from fact_ledger.settings import get_settings

pytestmark = pytest.mark.unit


class _Greeting(BaseModel):
    text: str


class _GreetingWithMood(BaseModel):
    text: str
    mood: str = "calm"


class _CountingStub:
    """A ``Complete`` that counts its calls and answers with ``schema(text=...)``."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__[M: BaseModel](self, system: str, user: str, schema: type[M]) -> M:
        self.calls += 1
        return schema.model_validate({"text": f"{system}|{user}"})


def test_an_unset_model_raises_before_any_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FACT_LEDGER_LLM_MODEL", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="FACT_LEDGER_LLM_MODEL"):
        llm.complete("system prompt", "user prompt", _Greeting)


@pytest.mark.slow
def test_complete_validates_the_mock_response_against_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import litellm  # noqa: PLC0415 -- not at module level: keeps this import out of fast test runs

    monkeypatch.setenv("FACT_LEDGER_LLM_MODEL", "anthropic/claude-haiku-4-5")
    get_settings.cache_clear()
    monkeypatch.setattr(
        litellm,
        "completion",
        functools.partial(litellm.completion, mock_response='{"text": "hi"}'),
    )

    result = llm.complete("system prompt", "user prompt", _Greeting)

    assert result == _Greeting(text="hi")


@pytest.mark.slow
def test_an_output_that_fails_the_schema_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import litellm  # noqa: PLC0415 -- not at module level: keeps this import out of fast test runs

    monkeypatch.setenv("FACT_LEDGER_LLM_MODEL", "anthropic/claude-haiku-4-5")
    get_settings.cache_clear()
    monkeypatch.setattr(
        litellm,
        "completion",
        functools.partial(litellm.completion, mock_response='{"wrong_field": "hi"}'),
    )

    with pytest.raises(ValueError, match="text"):
        llm.complete("system prompt", "user prompt", _Greeting)


def test_a_second_identical_call_hits_the_cache_and_creates_the_missing_directory(
    tmp_path: Path,
) -> None:
    cache_dir = tmp_path / "a" / "b"
    stub = _CountingStub()
    wrapped = llm.cached(stub, cache_dir, "m1")

    first = wrapped("sys", "usr", _Greeting)
    second = wrapped("sys", "usr", _Greeting)

    assert cache_dir.is_dir()
    assert stub.calls == 1
    assert first == second
    assert len(list(cache_dir.iterdir())) == 1

    rewrapped = llm.cached(stub, cache_dir, "m1")
    third = rewrapped("sys", "usr", _Greeting)

    assert stub.calls == 1
    assert third == first


@pytest.mark.parametrize(
    ("system", "user", "model", "schema"),
    [
        ("sys!", "usr", "m1", _Greeting),
        ("sys", "usr2", "m1", _Greeting),
        ("sys", "usr", "m2", _Greeting),
        ("sys", "usr", "m1", _GreetingWithMood),
    ],
    ids=["system", "user", "model", "schema"],
)
def test_a_change_in_any_part_of_the_key_misses_and_writes_a_second_file(
    tmp_path: Path, system: str, user: str, model: str, schema: type[BaseModel]
) -> None:
    cache_dir = tmp_path / "a" / "b"
    stub = _CountingStub()
    llm.cached(stub, cache_dir, "m1")("sys", "usr", _Greeting)
    assert stub.calls == 1

    llm.cached(stub, cache_dir, model)(system, user, schema)

    assert stub.calls == 2
    assert len(list(cache_dir.iterdir())) == 2
