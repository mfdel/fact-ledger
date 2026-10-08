"""The fact store: one Core table per record, mapped by field name.

Pydantic does the type conversion in both directions (``model_dump`` to write,
``model_validate`` to read), so there are no per-field mapping functions.
"""

from collections import Counter
from collections.abc import Sequence, Set
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Engine,
    ForeignKey,
    Index,
    Integer,
    Row,
    String,
    Table,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Connection, Dialect, ScalarResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.types import TypeDecorator

from fact_ledger.domain import Observation, Period
from fact_ledger.store.db import Base


class DecimalText(TypeDecorator[Decimal]):
    """Store a Decimal as its exact text.

    SQLite ``Numeric`` goes through float: it loses digits past about 15 significant
    figures and drops trailing zeros. Text keeps the digits a source actually states.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Decimal | None, dialect: Dialect) -> str | None:
        return None if value is None else str(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> Decimal | None:
        return None if value is None else Decimal(value)


observations = Table(
    "observations",
    Base.metadata,
    Column("observation_id", String, primary_key=True),
    Column("entity_id", String, nullable=False),
    Column("metric_id", String, nullable=False),
    Column("value", DecimalText, nullable=False),
    Column("unit", String, nullable=False),
    Column("currency", String(3), nullable=True),
    Column("stated_precision", DecimalText, nullable=True),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("period_type", String, nullable=False),
    Column("as_of_date", Date, nullable=False),
    Column("published_date", Date, nullable=False),
    Column("origin_id", String, nullable=False),
    Column("cited_origin_id", String, nullable=True),
    Column("document_id", String, nullable=False),
    Column("locator", String, nullable=False),
    Column("source_type", String, nullable=False),
    Column("reliability", Integer, nullable=False),
    Column("bias_direction", String, nullable=False),
    Column("segment", String, nullable=True),
    Column("region", String, nullable=True),
    Column("basis", String, nullable=False),
    Column("stated_label", String, nullable=False),
    Column("definition_status", String, nullable=False),
    Column("candidate_metric_ids", JSON, nullable=False),
    Column("derivation", JSON(none_as_null=True), nullable=True),
    Column("confidence", Integer, nullable=True),
    Index("ix_observations_entity_metric_period", "entity_id", "metric_id", "period_end"),
)

# S1-07 writes to this table. No reader yet.
metric_id_changes = Table(
    "metric_id_changes",
    Base.metadata,
    Column("change_id", Integer, primary_key=True, autoincrement=True),
    Column("observation_id", String, ForeignKey("observations.observation_id"), nullable=False),
    Column("old_metric_id", String, nullable=False),
    Column("new_metric_id", String, nullable=False),
    Column("changed_at", DateTime(timezone=True), nullable=False),
)


class FactStoreError(ValueError):
    """Raised when a batch fails a pre-insert check."""


def remap_observation(
    observation: Observation, old_metric_id: str, new_metric_id: str
) -> Observation | None:
    """Replace ``old_metric_id`` with ``new_metric_id`` in ``metric_id`` and in
    ``candidate_metric_ids``, keeping candidate order and dropping a repeat.
    Returns ``None`` if the observation does not use ``old_metric_id``.

    Pure and side-effect free, so the CLI can validate a whole map in memory, before it
    writes the dictionary alias, and before ``FactStore.remap_metric`` writes the database:
    a row that would map into its own candidates then fails with nothing changed anywhere.
    """
    if old_metric_id not in (observation.metric_id, *observation.candidate_metric_ids):
        return None
    metric_id = new_metric_id if observation.metric_id == old_metric_id else observation.metric_id
    candidates = tuple(
        dict.fromkeys(
            new_metric_id if candidate == old_metric_id else candidate
            for candidate in observation.candidate_metric_ids
        )
    )
    fields = observation.model_dump()
    fields.update(metric_id=metric_id, candidate_metric_ids=candidates)
    try:
        return Observation(**fields)
    except ValidationError as exc:
        msg = f"{observation.observation_id}: {exc}"
        raise FactStoreError(msg) from exc


class FactStore:
    def __init__(self, engine: Engine, identity_ids: Set[str]) -> None:
        self._engine = engine
        self._identity_ids = frozenset(identity_ids)

    def dispose(self) -> None:
        """Release the engine's connection pool. The CLI, a short process, calls this on exit."""
        self._engine.dispose()

    def add_many(self, batch: Sequence[Observation]) -> None:
        """Insert every observation in one transaction, or none of them."""
        if not batch:
            return
        self._reject_unknown_identities(batch)
        try:
            with self._engine.begin() as connection:
                self._reject_duplicates(connection, batch)
                connection.execute(insert(observations), [obs.model_dump() for obs in batch])
        except IntegrityError:
            # A concurrent writer used an id after the check. The batch is rolled back, so a
            # second check sees the rows of the other writer and names the ids.
            with self._engine.connect() as connection:
                self._reject_duplicates(connection, batch)
            raise

    def get(self, observation_id: str) -> Observation | None:
        with self._engine.connect() as connection:
            row = connection.execute(
                select(observations).where(observations.c.observation_id == observation_id)
            ).first()
        return None if row is None else self._to_observation(row)

    def find(
        self,
        entity_id: str | None = None,
        metric_id: str | None = None,
        period: Period | None = None,
    ) -> list[Observation]:
        """Filters combine with AND. ``period`` matches start, end and type exactly:
        several period types can share a ``period_end``.
        """
        query = select(observations)
        if entity_id is not None:
            query = query.where(observations.c.entity_id == entity_id)
        if metric_id is not None:
            query = query.where(observations.c.metric_id == metric_id)
        if period is not None:
            query = query.where(
                observations.c.period_start == period.start,
                observations.c.period_end == period.end,
                observations.c.period_type == period.type,
            )
        query = query.order_by(
            observations.c.entity_id,
            observations.c.metric_id,
            observations.c.period_end,
            observations.c.period_start,
            observations.c.observation_id,
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).all()
        return [self._to_observation(row) for row in rows]

    def remap_metric(self, old_metric_id: str, new_metric_id: str) -> list[str]:
        """Move every observation that uses ``old_metric_id`` to ``new_metric_id``, in one
        transaction. Records one ``metric_id_changes`` row per
        moved observation, so the git history of the dictionary is not the only trace of
        the move (the provenance record the story needs for "map back").
        """
        changed_ids: list[str] = []
        changed_at = datetime.now(UTC)
        with self._engine.begin() as connection:
            rows = connection.execute(select(observations)).all()
            for row in rows:
                observation = self._to_observation(row)
                updated = remap_observation(observation, old_metric_id, new_metric_id)
                if updated is None:
                    continue
                connection.execute(
                    update(observations)
                    .where(observations.c.observation_id == observation.observation_id)
                    .values(
                        metric_id=updated.metric_id,
                        candidate_metric_ids=list(updated.candidate_metric_ids),
                    )
                )
                connection.execute(
                    insert(metric_id_changes).values(
                        observation_id=observation.observation_id,
                        old_metric_id=old_metric_id,
                        new_metric_id=new_metric_id,
                        changed_at=changed_at,
                    )
                )
                changed_ids.append(observation.observation_id)
        return changed_ids

    @staticmethod
    def _to_observation(row: Row[Any]) -> Observation:
        return Observation.model_validate(row._mapping)

    def _reject_unknown_identities(self, batch: Sequence[Observation]) -> None:
        unknown = sorted(
            {
                obs.derivation.identity_id
                for obs in batch
                if obs.derivation is not None
                and obs.derivation.identity_id not in self._identity_ids
            }
        )
        if unknown:
            msg = f"unknown identity id(s): {', '.join(unknown)}"
            raise FactStoreError(msg)

    def _reject_duplicates(self, connection: Connection, batch: Sequence[Observation]) -> None:
        ids = [obs.observation_id for obs in batch]
        in_batch = {id_ for id_, count in Counter(ids).items() if count > 1}
        existing: ScalarResult[str] = connection.execute(
            select(observations.c.observation_id).where(observations.c.observation_id.in_(ids))
        ).scalars()
        duplicates = sorted(in_batch | set(existing))
        if duplicates:
            msg = f"observation_id already used: {', '.join(duplicates)}"
            raise FactStoreError(msg)
