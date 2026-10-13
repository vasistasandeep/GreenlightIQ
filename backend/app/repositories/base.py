"""Base repository pattern and the typed optimistic-lock conflict error (task 6).

Every concrete repository is an async class that receives an
:class:`~sqlalchemy.ext.asyncio.AsyncSession` by injection and exposes focused
CRUD helpers over a single ORM model. Shared logic (``get``, ``create``,
``list``, generic ``update``) lives here so individual repositories stay thin.

Optimistic locking (R27.2)
--------------------------
``titles`` and ``financial_projections`` carry a ``row_version`` column that
increments on every write. The :meth:`BaseRepository.update_with_version`
helper performs a conditional ``UPDATE ... WHERE pk = :id AND row_version =
:expected`` and raises :class:`OptimisticLockError` when no row matches — i.e.
the caller held a stale version. Task 6.2's error envelope maps this to
``409 STALE_VERSION``; task 6.3's integration test exercises the conflict path.

.. note::
   :class:`OptimisticLockError` is defined locally so the repository layer has
   no dependency on code that lands in a later task. When ``app/core/errors.py``
   (task 6.2) exists it should re-export / subclass this exception (or this
   module should import it from there) so a single type maps to
   ``409 STALE_VERSION`` across the stack.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class OptimisticLockError(Exception):
    """Raised when a versioned update is rejected because of a stale version.

    Signals that the ``row_version`` the caller supplied no longer matches the
    stored row (a concurrent writer advanced it). The error envelope (task 6.2)
    maps this to HTTP ``409`` with ``error_code = "STALE_VERSION"`` (R27.2).

    Attributes:
        entity: The table/entity name whose update was rejected.
        entity_id: The primary-key value of the targeted row.
        expected_version: The ``row_version`` the caller believed was current.
    """

    error_code = "STALE_VERSION"

    def __init__(
        self,
        entity: str,
        entity_id: Any,
        expected_version: int,
    ) -> None:
        self.entity = entity
        self.entity_id = entity_id
        self.expected_version = expected_version
        super().__init__(
            f"Stale version for {entity} {entity_id!r}: "
            f"expected row_version={expected_version}, row has been modified."
        )


class BaseRepository(Generic[ModelT]):
    """Async repository over a single ORM ``model`` using an injected session.

    Subclasses set :attr:`model` and :attr:`pk` (the primary-key column) and may
    add model-specific query methods. All methods ``flush`` rather than
    ``commit`` so the surrounding unit-of-work (request/task) controls the
    transaction boundary.
    """

    model: type[ModelT]
    pk: InstrumentedAttribute[Any]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entity_id: Any) -> ModelT | None:
        """Return the row with primary key ``entity_id`` or ``None``."""
        return await self.session.get(self.model, entity_id)

    async def list(self, *, limit: int | None = None, offset: int = 0) -> list[ModelT]:
        """Return rows for this model with optional pagination."""
        stmt = select(self.model).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, instance: ModelT) -> ModelT:
        """Persist a new ORM ``instance`` and flush so server defaults populate."""
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def update(self, instance: ModelT, **values: Any) -> ModelT:
        """Apply ``values`` to a managed ``instance`` and flush.

        Use :meth:`update_with_version` for optimistic-lock-protected tables.
        """
        for key, value in values.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, instance: ModelT) -> None:
        """Delete a managed ``instance`` and flush."""
        await self.session.delete(instance)
        await self.session.flush()

    async def update_with_version(
        self,
        entity_id: Any,
        expected_version: int,
        **values: Any,
    ) -> ModelT:
        """Optimistically update a ``row_version``-guarded row (R27.2).

        Issues ``UPDATE ... SET ..., row_version = row_version + 1
        WHERE pk = :id AND row_version = :expected``. If no row matches the
        version guard the stored row was modified concurrently and
        :class:`OptimisticLockError` is raised. On success the refreshed,
        version-incremented instance is returned.

        Args:
            entity_id: Primary-key value of the row to update.
            expected_version: The ``row_version`` the caller last read.
            **values: Column/value pairs to assign (``row_version`` is managed
                here and must not be supplied).

        Raises:
            OptimisticLockError: The row no longer exists at
                ``expected_version`` (stale version or missing row).
        """
        if not hasattr(self.model, "row_version"):
            raise AttributeError(
                f"{self.model.__name__} has no row_version column; "
                "update_with_version is only valid for optimistic-lock tables."
            )
        values.pop("row_version", None)

        version_col = self.model.row_version  # type: ignore[attr-defined]
        # Resolve the primary-key column from the MODEL CLASS, not ``self.pk``.
        # ``pk`` is a class attribute holding an ORM ``InstrumentedAttribute``;
        # reading it as ``self.pk`` (off a repository *instance*) re-invokes the
        # attribute descriptor with the repository as the target, which is not a
        # mapped object and raises ``UnmappedInstanceError``. Accessing it via the
        # class (``type(self).pk``) returns the column expression unchanged.
        pk_col = type(self).pk
        stmt = (
            update(self.model)
            .where(pk_col == entity_id, version_col == expected_version)
            .values(**values, row_version=version_col + 1)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        if result.rowcount == 0:
            raise OptimisticLockError(
                self.model.__tablename__, entity_id, expected_version
            )
        await self.session.flush()
        # Ensure the identity-map copy reflects the new row_version and values.
        instance = await self.session.get(self.model, entity_id)
        if instance is not None:
            await self.session.refresh(instance)
        return instance  # type: ignore[return-value]
