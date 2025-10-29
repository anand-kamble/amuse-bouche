"""Generic data access object pattern for SQLAlchemy models.

Provides an abstract base class with pooled session management, standard CRUD operations,
and optional fire-and-forget execution. Subclasses must implement the :py:attr:`model` property
to specify their target SQLAlchemy ORM model.
"""

from __future__ import annotations

import asyncio
import os
import threading
from abc import ABC, abstractmethod
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from typing import (
    Any,
    Callable,
    ClassVar,
    Generic,
    Iterator,
    List,
    Optional,
    TypeVar,
)

from sqlalchemy.orm import Session

from database.psql_connection import PostgresConnection
from utils.logger import Logger

#: Type variable for the SQLAlchemy model class.
ModelT = TypeVar("ModelT")
#: Type variable for the primary key type.
IdT = TypeVar("IdT")
#: Type variable for synchronous operation results.
SyncResultT = TypeVar("SyncResultT")


class DataAccessObject(Generic[ModelT, IdT], ABC):
    """Provide managed CRUD operations for a SQLAlchemy model.

    Generic abstract base class encapsulating session lifecycle, connection pooling,
    and common database operations. Subclasses specify a target ORM model via the
    :py:attr:`model` property and inherit synchronous CRUD methods (:py:meth:`get`,
    :py:meth:`create`, :py:meth:`update`, etc.) plus optional fire-and-forget variants
    (``*_ff``) that return :py:class:`concurrent.futures.Future` instances.

    All synchronous operations automatically manage sessions and expunge results
    to ensure detached instances.

    Attributes:
        _pg: Connection pool manager for this DAO instance.
        _logger: Logger instance named after the subclass.
        _bg_executor: Shared thread pool for fire-and-forget operations (lazily initialized).
        _bg_lock: Lock protecting executor initialization.

    See Also:
        :py:class:`database.psql_connection.PostgresConnection`
    """

    def __init__(
        self,
        *,
        database_name: str | None = None,
        min_connections: int = 1,
        max_connections: int = 10,
    ) -> None:
        """Initialize a DAO with a dedicated connection pool.

        Args:
            database_name: Target PostgreSQL database name; defaults to empty string.
            min_connections: Minimum pool size.
            max_connections: Maximum pool size.
        """
        self._pg = PostgresConnection(
            database_name=database_name or "",
            min_connections=min_connections,
            max_connections=max_connections,
        )
        self._logger: Logger = Logger(name=self.__class__.__name__)

    #: Shared thread pool for fire-and-forget operations, lazily initialized.
    _bg_executor: ClassVar[ThreadPoolExecutor | None] = None
    #: Lock protecting executor initialization.
    _bg_lock: ClassVar[threading.Lock] = threading.Lock()

    @property
    @abstractmethod
    def model(self) -> type[ModelT]:
        """Return the SQLAlchemy ORM model class managed by this DAO.

        Subclasses must implement this property to specify the target model.

        Returns:
            The SQLAlchemy declarative model class.
        """
        raise NotImplementedError

    @property
    def primary_key_attribute_name(self) -> str:
        """Return the primary key attribute name for the model.

        Override this property if the primary key is not named ``id``.

        Returns:
            Primary key attribute name; defaults to ``"id"``.
        """
        return "id"

    def _get_pk_column(self) -> Any:
        """Retrieve the primary key column from the model.

        Returns:
            The SQLAlchemy column object for the primary key.
        """
        return getattr(self.model, self.primary_key_attribute_name)

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Provide a managed SQLAlchemy session context.

        Yields a session from this DAO's connection pool and ensures proper cleanup.

        Yields:
            A :py:class:`sqlalchemy.orm.Session` instance.

        Examples:
            >>> with dao.session_scope() as session:
            ...     result = session.query(Model).all()
        """
        with self._pg.get_session() as session:
            yield session

    def _run_in_session(self, fn: Callable[[Session], SyncResultT]) -> SyncResultT:
        """Execute a callable within a managed session.

        Args:
            fn: Callable receiving a :py:class:`~sqlalchemy.orm.Session` and returning a result.

        Returns:
            The result of invoking ``fn``.
        """
        with self.session_scope() as session:
            return fn(session)

    async def _run_in_session_async(
        self, fn: Callable[[Session], SyncResultT]
    ) -> SyncResultT:
        """Execute a synchronous callable in a background thread and await its result.

        Args:
            fn: Callable receiving a :py:class:`~sqlalchemy.orm.Session` and returning a result.

        Returns:
            The result of invoking ``fn`` in a worker thread.
        """
        return await asyncio.to_thread(self._run_in_session, fn)

    # ---- Background execution helpers ---------------------------------------
    @classmethod
    def _get_bg_executor(cls) -> ThreadPoolExecutor:
        """Retrieve or lazily initialize the shared background thread pool.

        Returns:
            Shared :py:class:`~concurrent.futures.ThreadPoolExecutor` instance.
        """
        if cls._bg_executor is None:
            with cls._bg_lock:
                if cls._bg_executor is None:
                    max_workers = max(4, (os.cpu_count() or 1))
                    cls._bg_executor = ThreadPoolExecutor(
                        max_workers=max_workers, thread_name_prefix="dao-bg"
                    )
        return cls._bg_executor

    def _submit_background(
        self, fn: Callable[[Session], SyncResultT]
    ) -> Future[SyncResultT]:
        """Submit a callable to run in the background thread pool.

        Wraps the callable with session management and error logging.

        Args:
            fn: Callable receiving a :py:class:`~sqlalchemy.orm.Session` and returning a result.

        Returns:
            A :py:class:`~concurrent.futures.Future` that will hold the result or exception.
        """

        def _runner() -> SyncResultT:
            try:
                return self._run_in_session(fn)
            except Exception as e:  # pragma: no cover - defensive logging
                print(str(e))
                self._logger.error(
                    "Background DAO operation failed",
                    exception=e,
                    logger_name=self.__class__.__name__,
                )
                raise

        return self._get_bg_executor().submit(_runner)

    # ---- Generic CRUD helpers (READ - synchronous) ---------------------------
    def get(self, id_value: IdT) -> Optional[ModelT]:
        """Fetch a single model instance by primary key.

        Args:
            id_value: Primary key value to look up.

        Returns:
            The detached model instance, or ``None`` if not found.
        """

        def _op(session: Session) -> Optional[ModelT]:
            model_any: Any = self.model
            row = session.get(model_any, id_value)
            if row is not None:
                session.expunge(row)
            return row

        return self._run_in_session(_op)

    def list(self, *, limit: int = 100, offset: int = 0) -> List[ModelT]:
        """Retrieve a paginated list of model instances.

        Args:
            limit: Maximum number of rows to return; defaults to 100.
            offset: Number of rows to skip; defaults to 0.

        Returns:
            List of detached model instances.
        """

        def _op(session: Session) -> List[ModelT]:
            model_any = self.model
            q = session.query(model_any)
            if offset > 0:
                q = q.offset(offset)
            if limit > 0:
                q = q.limit(limit)
            rows = list(q.all())
            for row in rows:
                session.expunge(row)
            return rows

        return self._run_in_session(_op)

    def list_by(
        self, limit: int = 100, offset: int = 0, **filters: Any
    ) -> List[ModelT]:
        """Retrieve a filtered, paginated list of model instances.

        Args:
            limit: Maximum number of rows to return; defaults to 100.
            offset: Number of rows to skip; defaults to 0.
            **filters: Attribute equality filters applied via ``filter_by``.

        Returns:
            List of detached model instances matching the filters.

        Examples:
            >>> dao.list_by(limit=50, status="active", role="admin")
        """

        def _op(session: Session) -> List[ModelT]:
            q = session.query(self.model).filter_by(**filters)
            if offset > 0:
                q = q.offset(offset)
            if limit > 0:
                q = q.limit(limit)
            rows = list(q.all())
            for row in rows:
                session.expunge(row)
            return rows

        return self._run_in_session(_op)

    def list_by_order_by(
        self, order_by: Any, *, limit: int = 100, offset: int = 0, **filters: Any
    ) -> List[ModelT]:
        """Retrieve a filtered, sorted, paginated list of model instances.

        Args:
            order_by: SQLAlchemy order expression (e.g., ``Model.created_at.desc()``).
            limit: Maximum number of rows to return; defaults to 100.
            offset: Number of rows to skip; defaults to 0.
            **filters: Attribute equality filters applied via ``filter_by``.

        Returns:
            List of detached model instances matching the filters, sorted as specified.

        Examples:
            >>> dao.list_by_order_by(Model.created_at.desc(), limit=10, active=True)
        """

        def _op(session: Session) -> List[ModelT]:
            q = session.query(self.model).filter_by(**filters).order_by(order_by)
            if offset > 0:
                q = q.offset(offset)
            if limit > 0:
                q = q.limit(limit)
            rows = list(q.all())
            for row in rows:
                session.expunge(row)
            return rows

        return self._run_in_session(_op)

    def exists(self, id_value: IdT) -> ModelT | None:
        """Check existence by primary key and return the instance if found.

        Args:
            id_value: Primary key value to look up.

        Returns:
            The detached model instance, or ``None`` if not found.
        """

        def _op(session: Session) -> ModelT | None:
            pk_col = self._get_pk_column()
            res = session.query(self.model).filter(pk_col == id_value).first()
            if res is not None:
                session.expunge(res)
            return res

        return self._run_in_session(_op)

    # ---- Generic CRUD helpers (WRITE - synchronous) ---------------------------
    def create(self, **fields: Any) -> ModelT:
        """Create a new model instance in the database.

        Args:
            **fields: Attributes to set on the new instance.

        Returns:
            The detached, persisted model instance with primary key assigned.

        Examples:
            >>> user = dao.create(name="Alice", email="alice@example.com")
        """

        def _write(session: Session) -> ModelT:
            row = self.model(**fields)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

        return self._run_in_session(_write)

    def update(self, id_value: IdT, **fields: Any) -> Optional[ModelT]:
        """Update an existing model instance by primary key.

        Args:
            id_value: Primary key value identifying the row to update.
            **fields: Attributes to update.

        Returns:
            The detached, updated model instance, or ``None`` if not found.

        Examples:
            >>> updated_user = dao.update(42, email="newemail@example.com")
        """

        def _write(session: Session) -> Optional[ModelT]:
            row = session.get(self.model, id_value)
            if row is None:
                return None
            for key, value in fields.items():
                setattr(row, key, value)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row

        return self._run_in_session(_write)

    def upsert(self, id_value: IdT, /, **fields: Any) -> ModelT:
        """Insert a new row or update an existing one by primary key.

        Args:
            id_value: Primary key value; if found, updates; otherwise creates.
            **fields: Attributes to set or update.

        Returns:
            The detached model instance (either created or updated).

        Examples:
            >>> user = dao.upsert(42, name="Bob", email="bob@example.com")
        """

        def _write(session: Session) -> ModelT:
            model_class: Any = self.model
            existing_row = session.get(model_class, id_value)
            if existing_row is None:
                row_data: dict[str, Any] = {self.primary_key_attribute_name: id_value}
                row_data.update(fields)
                new_row = model_class(**row_data)
                session.add(new_row)
                session.flush()
                session.refresh(new_row)
                session.expunge(new_row)
                return new_row

            for key, value in fields.items():
                setattr(existing_row, key, value)
            session.flush()
            session.refresh(existing_row)
            session.expunge(existing_row)
            return existing_row

        return self._run_in_session(_write)

    def delete(self, id_value: IdT) -> bool:
        """Delete a model instance by primary key.

        Args:
            id_value: Primary key value identifying the row to delete.

        Returns:
            ``True`` if the row was found and deleted, ``False`` otherwise.

        Examples:
            >>> was_deleted = dao.delete(42)
        """

        def _write(session: Session) -> bool:
            row = session.get(self.model, id_value)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True

        return self._run_in_session(_write)

    # ---- Fire-and-forget counterparts (return Future) -----------------------
    def create_ff(self, **fields: Any) -> Future[ModelT]:
        """Submit a create operation to run asynchronously in the background.

        Args:
            **fields: Attributes to set on the new instance.

        Returns:
            A :py:class:`~concurrent.futures.Future` yielding the detached model instance.

        See Also:
            :py:meth:`create`
        """

        def _write(session: Session) -> ModelT:
            row_any: Any = self.model(**fields)
            session.add(row_any)
            session.flush()
            session.refresh(row_any)
            session.expunge(row_any)
            return row_any

        return self._submit_background(_write)

    def update_ff(self, id_value: IdT, **fields: Any) -> Future[Optional[ModelT]]:
        """Submit an update operation to run asynchronously in the background.

        Args:
            id_value: Primary key value identifying the row to update.
            **fields: Attributes to update.

        Returns:
            A :py:class:`~concurrent.futures.Future` yielding the updated instance or ``None``.

        See Also:
            :py:meth:`update`
        """
        return self._submit_background(lambda session: self.update(id_value, **fields))

    def upsert_ff(self, id_value: IdT, /, **fields: Any) -> Future[ModelT]:
        """Submit an upsert operation to run asynchronously in the background.

        Args:
            id_value: Primary key value; if found, updates; otherwise creates.
            **fields: Attributes to set or update.

        Returns:
            A :py:class:`~concurrent.futures.Future` yielding the model instance.

        See Also:
            :py:meth:`upsert`
        """
        return self._submit_background(lambda session: self.upsert(id_value, **fields))

    def delete_ff(self, id_value: IdT) -> Future[bool]:
        """Submit a delete operation to run asynchronously in the background.

        Args:
            id_value: Primary key value identifying the row to delete.

        Returns:
            A :py:class:`~concurrent.futures.Future` yielding ``True`` if deleted, ``False`` otherwise.

        See Also:
            :py:meth:`delete`
        """

        def _write(session: Session) -> bool:
            model_any: Any = self.model
            row = session.get(model_any, id_value)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True

        return self._submit_background(_write)

    # ---- Utility hooks --------------------------------------------------------
    def run_custom(self, fn: Callable[[Session], SyncResultT]) -> SyncResultT:
        """Execute a custom callable within a managed session.

        Use this method to run arbitrary queries or operations not covered by standard CRUD methods.

        Args:
            fn: Callable receiving a :py:class:`~sqlalchemy.orm.Session` and returning a result.

        Returns:
            The result of invoking ``fn``.

        Examples:
            >>> def complex_query(session: Session) -> List[Model]:
            ...     return session.query(Model).filter(...).all()
            >>> results = dao.run_custom(complex_query)
        """
        return self._run_in_session(fn)

    def close(self) -> None:
        """Dispose the connection pool and clean up resources.

        Should be called when the DAO is no longer needed to release database connections.
        Logs errors if disposal fails.
        """
        try:
            self._pg.close_engine()
        except Exception as e:
            print(str(e))
            self._logger.error(
                "Failed to close database engine",
                exception=e,
                logger_name=self.__class__.__name__,
            )
