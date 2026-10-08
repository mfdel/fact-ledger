"""One LLM call. The only module that imports
LiteLLM: ``import litellm`` costs about 7s, and the CLI imports every command module at
start, so the import stays inside ``complete`` rather than at module load time.
"""

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from fact_ledger.settings import get_settings


def complete[M: BaseModel](system: str, user: str, schema: type[M]) -> M:
    """One page, one call. Raises ``ValueError`` if no model is configured or the
    response fails ``schema`` (``pydantic.ValidationError`` is already a ``ValueError``).
    """
    settings = get_settings()
    if settings.llm_model is None:
        msg = "set FACT_LEDGER_LLM_MODEL to a LiteLLM model string"
        raise ValueError(msg)

    # Without this, LiteLLM downloads its cost map from GitHub on import. The product
    # tracks no cost, so that outbound call is pure overhead.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm  # noqa: PLC0415 -- see module docstring

    response = litellm.completion(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=schema,
    )
    content: str = response.choices[0].message.content
    return schema.model_validate_json(content)


def cached[M: BaseModel](
    complete: Callable[[str, str, type[M]], M], cache_dir: Path, model: str
) -> Callable[[str, str, type[M]], M]:
    """Answer from ``cache_dir`` when the same model, prompt and schema ran before. The
    schema is in the key so that a changed schema never replays an answer of the old shape.
    """

    def call(system: str, user: str, schema: type[M]) -> M:
        payload = json.dumps([model, system, user, schema.model_json_schema()], sort_keys=True)
        path = cache_dir / f"{hashlib.sha256(payload.encode()).hexdigest()}.json"
        if path.exists():
            return schema.model_validate_json(path.read_text())
        answer = complete(system, user, schema)
        # Created after the call: a failed call leaves no empty directory behind.
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(answer.model_dump_json())
        return answer

    return call
