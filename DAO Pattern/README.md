# Simplify Your SQLAlchemy: A Guide to the DAO Pattern

_Hatched at Liebre.ai—less boilerplate, more signal._


## Introduction: The ORM Paradox – A Deal with the Devil?

Object-Relational Mappers (ORMs) promise a better way to work with databases. They let you manipulate data using Python objects instead of raw SQL queries. **SQLAlchemy** sits at the top of the Python ORM world—it's incredibly powerful, endlessly flexible, and can handle just about any database scenario you throw at it.

But that power comes at a cost: boilerplate code, cognitive overload, and performance traps lurking around every corner.

We love SQLAlchemy's capabilities, but its complexity can be overwhelming. The main pain points boil down to **four core challenges**:

1. Complex **Session management**
2. Mountains of **boilerplate code**
3. Hidden **performance pitfalls**
4. The async/sync divide in **asynchronous programming**

This guide is about taming the complexity. We'll build a **Data Access Object (DAO)**—not as a heavyweight enterprise pattern, but as a simple, practical wrapper. Think of it as a sanity layer that lets you harness SQLAlchemy's power without getting lost in its complexity.

---

## Part I: The Trials of a SQLAlchemy Alchemist

To appreciate the solution, we need to understand the problem. If you've worked with SQLAlchemy in production, these challenges will feel familiar.

### The Labyrinth of Sessions: State, Lies, and DetachedInstanceError

The SQLAlchemy `Session` isn't just a database connection—it's a stateful workbench that tracks and manages your objects. Every object goes through a lifecycle with distinct states:

- **Transient**: A plain Python object with no database connection
- **Pending**: Added to the session via `session.add()`, waiting to be saved
- **Persistent**: After `flush()` or `commit()`, synchronized with a database row
- **Detached**: When the session closes, the object loses its database connection

That last state is where **`DetachedInstanceError`** comes from—SQLAlchemy's most famous error. Here's the typical scenario: in a web app, you open a session for a request, fetch some data, close the session, then try to access a lazy-loaded relationship. The object remembers its ID, but it can't fetch the related data because it's been disconnected from the database.

#### The Root Problem

This isn't a bug—it's a fundamental design tension. SQLAlchemy's power comes from its stateful "unit of work" pattern, but this clashes with the stateless nature of modern web applications.

![Not bad. But not good.](https://media1.tenor.com/m/V0CT3rf7s-4AAAAd/not-bad-not-good.gif)

**A DAO bridges this gap**, ensuring objects are always fully loaded and usable when returned to your application code.

### The Boilerplate Tax: A Toll Paid on Every Project

Before writing your first query, you need to set up a lot of infrastructure. Every SQLAlchemy project requires the same repetitive setup:

1. **Database Configuration**: Creating the engine and connection string
2. **Session Management**: Defining the `sessionmaker` and lifecycle management (like FastAPI's `get_db`)
3. **Model Definitions**: Setting up `declarative_base` for your models
4. **Migration Setup**: Configuring Alembic's `env.py` to find your models and database

Search GitHub for "SQLAlchemy boilerplate" and you'll find hundreds of repositories. Everyone solving the same problem over and over.

#### The Framework Vacuum

SQLAlchemy is a **library**, not a framework—it gives you powerful tools but doesn't tell you how to structure your application. This flexibility is both a strength and a weakness. Every team ends up building their own mini-framework for data access.

**A DAO formalizes these common patterns**, providing a standard approach that reduces decision fatigue and turns SQLAlchemy into a more framework-like experience.

### The Seven Deadly Sins of Performance

> *The great beauty of an ORM is that it abstracts away SQL. The great danger of an ORM is that it abstracts away SQL.*

This paradox leads to performance nightmares where innocent-looking Python code hammers your database. Here are the most common sins:

#### 1. The `len()` Sloth
Loading thousands of records just to count them, instead of using a database-side `count()`.

#### 2. The Gluttony of Columns
Fetching entire objects with `SELECT *` when you only need one or two fields.

#### 3. The Wrath of the N+1 Query
The classic ORM trap. Looping over objects and accessing relationships triggers a separate query for each item, creating a query storm.

#### 4. The Greed of Bad Cascades
Misconfigured cascades that make SQLAlchemy issue hundreds of individual `DELETE` statements instead of letting the database handle it efficiently.

#### The Performance Gap

These aren't SQLAlchemy bugs—they're the result of abstraction. Writing performant queries requires understanding both the ORM's internals (`joinedload`, `selectinload`, etc.) and the SQL it generates. There's a big gap between code that works and code that performs well.

**A DAO implements "Performance by Convention"**—the easy way becomes the fast way because best practices are baked in.

### The Great Async Divide: A Tale of Two Syntaxes

When Python embraced async programming, SQLAlchemy adapted with versions 1.4 and 2.0. But this created a split—you now have two completely different syntaxes for the same operations.

Compare a simple query:

**Synchronous:**
```python
user = db.query(User).filter(User.id == user_id).first()
```

**Asynchronous:**
```python
result = await db.execute(select(User).where(User.id == user_id))
user = result.scalars().first()
```

The async version isn't just more verbose—it's a completely different mental model. The fluent `Query` API becomes a multi-step process: build a `select`, execute it, get a `Result`, extract scalars, then fetch the data.

Worse, running synchronous SQLAlchemy code in an async application blocks the event loop, making your app **slower** than it would be fully synchronous.

#### The Unified Solution

This split has fragmented documentation, tutorials, and community knowledge. Developers now need to learn two different approaches.

**A DAO provides a unified API**, hiding the complexity of both sync and async implementations behind consistent methods. Write once, deploy anywhere.

---

## Part II: Building the DAO, Step-by-Step

Now that we understand the problems, let's build the solution. We'll create a generic `DataAccessObject` class that wraps SQLAlchemy with sensible conventions.

### Step 1: The Foundation

We'll start with an abstract base class that works with any SQLAlchemy model:

```python
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
    """Provide managed CRUD operations for a SQLAlchemy model."""

    def __init__(
        self,
        *,
        database_name: str | None = None,
        min_connections: int = 1,
        max_connections: int = 10,
    ) -> None:
        """Initialize a DAO with a dedicated connection pool."""
        self._pg = PostgresConnection(
            database_name=database_name or "",
            min_connections=min_connections,
            max_connections=max_connections,
        )
        self._logger: Logger = Logger(name=self.__class__.__name__)

    @property
    @abstractmethod
    def model(self) -> type[ModelT]:
        """Return the SQLAlchemy ORM model class managed by this DAO."""
        raise NotImplementedError

    @property
    def primary_key_attribute_name(self) -> str:
        """Return the primary key attribute name for the model."""
        return "id"

    def _get_pk_column(self) -> Any:
        """Retrieve the primary key column from the model."""
        return getattr(self.model, self.primary_key_attribute_name)
```

This generic class takes a model type (`ModelT`) and a primary key type (`IdT`). The `__init__` method handles connection pooling automatically, and the abstract `model` property forces subclasses to declare which model they manage.

#### Key Design Decisions:

- **Connection Pooling**: Prevents connection exhaustion
- **Generic Types**: Full type safety with `Generic[ModelT, IdT]`
- **Flexible Primary Keys**: Override `primary_key_attribute_name` for non-standard keys
- **Logging**: Each DAO instance gets its own logger

### Step 2: Taming the Session

Now we tackle session management—the core of our solution:

```python
    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Provide a managed SQLAlchemy session context."""
        with self._pg.get_session() as session:
            yield session

    def _run_in_session(self, fn: Callable[[Session], SyncResultT]) -> SyncResultT:
        """Execute a callable within a managed session."""
        with self.session_scope() as session:
            return fn(session)

    async def _run_in_session_async(
        self, fn: Callable[[Session], SyncResultT]
    ) -> SyncResultT:
        """Execute a synchronous callable in a background thread and await its result."""
        return await asyncio.to_thread(self._run_in_session, fn)
```

The `session_scope` wraps the session lifecycle in a clean `with` statement. The `_run_in_session` helper executes any function within this managed scope. **This abstracts away all session handling** from our CRUD methods.

The `_run_in_session_async` method bridges to async code by running sync operations in a background thread, avoiding event loop blocking.

### Step 3: Implementing Read Operations

Now we can add read methods. **The crucial detail: using `session.expunge()` before returning objects.** This detaches them from the session, solving the `DetachedInstanceError` by returning clean, state-free objects.

```python
    def get(self, id_value: IdT) -> Optional[ModelT]:
        """Fetch a single model instance by primary key."""
        def _op(session: Session) -> Optional[ModelT]:
            model_any: Any = self.model
            row = session.get(model_any, id_value)
            if row is not None:
                session.expunge(row)
            return row
        return self._run_in_session(_op)

    def list(self, *, limit: int = 100, offset: int = 0) -> List[ModelT]:
        """Retrieve a paginated list of model instances."""
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
        """Retrieve a filtered, paginated list of model instances."""
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
```

Each method defines an inner function (`_op`) with the SQLAlchemy logic, then passes it to `_run_in_session`. This pattern is clean and ensures **every database interaction is safe**.

The DAO also provides `list_by_order_by` for sorted queries and `exists` for existence checks—all following the same pattern.

### Step 4: Implementing Write Operations

Write operations follow the same approach:

```python
    def create(self, **fields: Any) -> ModelT:
        """Create a new model instance in the database."""
        def _write(session: Session) -> ModelT:
            row = self.model(**fields)
            session.add(row)
            session.flush()
            session.refresh(row)
            session.expunge(row)
            return row
        return self._run_in_session(_write)

    def update(self, id_value: IdT, **fields: Any) -> Optional[ModelT]:
        """Update an existing model instance by primary key."""
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
        """Insert a new row or update an existing one by primary key."""
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
        """Delete a model instance by primary key."""
        def _write(session: Session) -> bool:
            row = session.get(self.model, id_value)
            if row is None:
                return False
            session.delete(row)
            session.flush()
            return True
        return self._run_in_session(_write)
```

The flow is critical:

1. `flush()` sends changes to the database
2. `refresh()` retrieves any new state (auto-generated IDs, defaults)
3. `expunge()` detaches the object for safe use outside the session

This ensures returned objects are **complete, consistent, and usable**.

### Step 5: Adding "Fire-and-Forget" Asynchronicity

For operations that don't need to block, we add "fire-and-forget" variants using a shared `ThreadPoolExecutor`:

```python
    #: Shared thread pool for fire-and-forget operations, lazily initialized.
    _bg_executor: ClassVar[ThreadPoolExecutor | None] = None
    #: Lock protecting executor initialization.
    _bg_lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def _get_bg_executor(cls) -> ThreadPoolExecutor:
        """Retrieve or lazily initialize the shared background thread pool."""
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
        """Submit a callable to run in the background thread pool."""
        def _runner() -> SyncResultT:
            try:
                return self._run_in_session(fn)
            except Exception as e:
                print(str(e))
                self._logger.error(
                    "Background DAO operation failed",
                    exception=e,
                    logger_name=self.__class__.__name__,
                )
                raise
        return self._get_bg_executor().submit(_runner)

    def create_ff(self, **fields: Any) -> Future[ModelT]:
        """Submit a create operation to run asynchronously in the background."""
        def _write(session: Session) -> ModelT:
            row_any: Any = self.model(**fields)
            session.add(row_any)
            session.flush()
            session.refresh(row_any)
            session.expunge(row_any)
            return row_any
        return self._submit_background(_write)

    # Similar methods: update_ff, upsert_ff, delete_ff
```

This provides a pragmatic way to offload database writes without fully converting to `asyncio`. The shared executor is lazily initialized and thread-safe.

### Step 6: Custom Operations and Cleanup

The DAO provides hooks for custom operations and resource cleanup:

```python
    def run_custom(self, fn: Callable[[Session], SyncResultT]) -> SyncResultT:
        """Execute a custom callable within a managed session.
        
        Use this method to run arbitrary queries or operations not covered 
        by standard CRUD methods.
        """
        return self._run_in_session(fn)

    def close(self) -> None:
        """Dispose the connection pool and clean up resources."""
        try:
            self._pg.close_engine()
        except Exception as e:
            print(str(e))
            self._logger.error(
                "Failed to close database engine",
                exception=e,
                logger_name=self.__class__.__name__,
            )
```

The `run_custom` method lets you execute complex queries that don't fit standard CRUD patterns while still benefiting from automatic session management.

### Step 7: Creating Your Custom DAO Classes

To use the DAO, create a subclass for each model. Here's a complete example:

```python
from sqlalchemy import Column, Integer, String, DateTime, Enum as SQLEnum
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
from typing import List, Optional
from enum import Enum
from sqlalchemy.orm import Session

Base = declarative_base()

# Define the model
class OrderStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Order(Base):
    __tablename__ = 'orders'
    
    order_id = Column(Integer, primary_key=True)
    customer_name = Column(String(100), nullable=False)
    customer_email = Column(String(100), nullable=False)
    total_amount = Column(Integer, nullable=False)  # Amount in cents
    status = Column(SQLEnum(OrderStatus), default=OrderStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Create the DAO with custom methods
class OrderDAO(DataAccessObject[Order, int]):
    """Data Access Object for Order model.
    
    Provides standard CRUD operations plus domain-specific methods
    for managing orders in the system.
    """
    
    def __init__(
        self,
        database_name: str | None = None,
        min_connections: int = 1,
        max_connections: int = 10,
    ):
        """Initialize OrderDAO with connection pool configuration."""
        super().__init__(
            database_name=database_name,
            min_connections=min_connections,
            max_connections=max_connections,
        )

    @property
    def model(self) -> type[Order]:
        """Return the Order model class."""
        return Order

    @property
    def primary_key_attribute_name(self) -> str:
        """Override to use 'order_id' instead of default 'id'."""
        return "order_id"

    # ---- Custom domain-specific methods ----

    def create_order(
        self,
        customer_name: str,
        customer_email: str,
        total_amount: int,
    ) -> Order:
        """Create a new order with initial PENDING status.
        
        Args:
            customer_name: Full name of the customer
            customer_email: Email address for order confirmation
            total_amount: Order total in cents (e.g., 1500 = $15.00)
            
        Returns:
            Newly created Order instance
        """
        return self.create(
            customer_name=customer_name,
            customer_email=customer_email,
            total_amount=total_amount,
            status=OrderStatus.PENDING,
        )

    def get_order_by_id(self, order_id: int) -> Optional[Order]:
        """Retrieve a single order by its ID.
        
        Args:
            order_id: The unique order identifier
            
        Returns:
            Order instance or None if not found
        """
        return self.get(order_id)

    def get_orders_by_customer_email(
        self,
        customer_email: str,
        limit: int = 50
    ) -> List[Order]:
        """Get all orders for a specific customer.
        
        Args:
            customer_email: Customer's email address
            limit: Maximum number of orders to return
            
        Returns:
            List of Order instances for this customer
        """
        return self.list_by(customer_email=customer_email, limit=limit)

    def get_orders_by_status(
        self,
        status: OrderStatus,
        limit: int = 100,
        offset: int = 0
    ) -> List[Order]:
        """Get all orders with a specific status.
        
        Args:
            status: The order status to filter by
            limit: Maximum number of results
            offset: Number of results to skip (for pagination)
            
        Returns:
            List of Order instances matching the status
        """
        return self.list_by(status=status, limit=limit, offset=offset)

    def get_recent_orders(
        self,
        limit: int = 10,
        status: Optional[OrderStatus] = None
    ) -> List[Order]:
        """Get the most recent orders, optionally filtered by status.
        
        Args:
            limit: Number of orders to return
            status: Optional status filter
            
        Returns:
            List of Order instances ordered by creation date (newest first)
        """
        if status:
            return self.list_by_order_by(
                Order.created_at.desc(),
                status=status,
                limit=limit,
            )
        else:
            # For all statuses, use run_custom
            def _get_recent(session: Session) -> List[Order]:
                orders = session.query(Order).order_by(
                    Order.created_at.desc()
                ).limit(limit).all()
                for order in orders:
                    session.expunge(order)
                return orders
            return self.run_custom(_get_recent)

    def mark_as_processing(self, order_id: int) -> Optional[Order]:
        """Update order status to PROCESSING.
        
        Args:
            order_id: The order to update
            
        Returns:
            Updated Order instance or None if not found
        """
        return self.update(order_id, status=OrderStatus.PROCESSING)

    def complete_order(self, order_id: int) -> Optional[Order]:
        """Mark an order as completed.
        
        Args:
            order_id: The order to complete
            
        Returns:
            Updated Order instance or None if not found
        """
        return self.update(order_id, status=OrderStatus.COMPLETED)

    def cancel_order(self, order_id: int) -> Optional[Order]:
        """Cancel an order.
        
        Args:
            order_id: The order to cancel
            
        Returns:
            Updated Order instance or None if not found
        """
        return self.update(order_id, status=OrderStatus.CANCELLED)

    def get_pending_orders_total(self) -> int:
        """Calculate total amount of all pending orders.
        
        Returns:
            Total amount in cents
        """
        from sqlalchemy import func
        
        def _calculate_total(session: Session) -> int:
            result = session.query(
                func.coalesce(func.sum(Order.total_amount), 0)
            ).filter(
                Order.status == OrderStatus.PENDING
            ).scalar()
            return int(result)
        
        return self.run_custom(_calculate_total)


# Usage Examples
order_dao = OrderDAO(database_name="ecommerce", max_connections=20)

# Create a new order
new_order = order_dao.create_order(
    customer_name="John Smith",
    customer_email="john@example.com",
    total_amount=4999,  # $49.99
)
print(f"Created order #{new_order.order_id}")

# Retrieve order by ID
order = order_dao.get_order_by_id(new_order.order_id)
if order:
    print(f"Order status: {order.status}")

# Get all orders for a customer
customer_orders = order_dao.get_orders_by_customer_email("john@example.com")
print(f"Customer has {len(customer_orders)} orders")

# Get pending orders
pending = order_dao.get_orders_by_status(OrderStatus.PENDING)
print(f"There are {len(pending)} pending orders")

# Get recent orders
recent = order_dao.get_recent_orders(limit=5)
for order in recent:
    print(f"Order #{order.order_id}: ${order.total_amount/100:.2f}")

# Update order status
order_dao.mark_as_processing(new_order.order_id)
order_dao.complete_order(new_order.order_id)

# Get business metrics
total_pending = order_dao.get_pending_orders_total()
print(f"Total pending: ${total_pending/100:.2f}")

# Fire-and-forget order creation (for high-throughput scenarios)
future_order = order_dao.create_ff(
    customer_name="Jane Doe",
    customer_email="jane@example.com",
    total_amount=2999,
    status=OrderStatus.PENDING,
)
# Continue with other work...
created_order = future_order.result()  # Get result when needed

# Cleanup
order_dao.close()
```

#### Key Points for Creating Custom DAOs:

1. **Always call `super().__init__()`** to initialize the base class with connection settings
2. **Implement the `model` property** to specify which SQLAlchemy model this DAO manages
3. **Override `primary_key_attribute_name`** if your primary key isn't named `id`
4. **Add domain-specific methods** that wrap the base CRUD operations with meaningful names
5. **Use type hints** for better IDE support and type checking
6. **Document your methods** with clear docstrings explaining parameters and return values
7. **Leverage `run_custom`** for complex queries that don't fit the standard patterns

---

## Practical Examples: Real-World Usage Patterns

Let's explore more detailed examples showing how to use the DAO pattern with SQLAlchemy models in various scenarios.

### Example 1: Simple Blog Post System

```python
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Session
from datetime import datetime
from typing import List, Optional

Base = declarative_base()

# Models
class Author(Base):
    __tablename__ = 'authors'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    bio = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    posts = relationship("Post", back_populates="author")


class Post(Base):
    __tablename__ = 'posts'
    
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author_id = Column(Integer, ForeignKey('authors.id'), nullable=False)
    published = Column(Integer, default=0)  # 0 = draft, 1 = published
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    author = relationship("Author", back_populates="posts")


# DAOs
class AuthorDAO(DataAccessObject[Author, int]):
    @property
    def model(self) -> type[Author]:
        return Author


class PostDAO(DataAccessObject[Post, int]):
    @property
    def model(self) -> type[Post]:
        return Post
```

### Example 2: Basic CRUD Operations

```python
# Initialize DAOs
author_dao = AuthorDAO(database_name="blog_db", max_connections=20)
post_dao = PostDAO(database_name="blog_db", max_connections=20)

# ============================================================
# CREATE Operations
# ============================================================

# Create a new author
author = author_dao.create(
    name="Jane Doe",
    email="jane.doe@example.com",
    bio="Full-stack developer and tech blogger"
)
print(f"Created author: {author.name} with ID: {author.id}")

# Create multiple posts for the author
post1 = post_dao.create(
    title="Introduction to Python",
    content="Python is a versatile programming language...",
    author_id=author.id,
    published=1
)

post2 = post_dao.create(
    title="Advanced SQLAlchemy Patterns",
    content="In this post, we'll explore advanced patterns...",
    author_id=author.id,
    published=0  # Draft
)

print(f"Created {post1.title} (published)")
print(f"Created {post2.title} (draft)")

# ============================================================
# READ Operations
# ============================================================

# Get a single author by ID
retrieved_author = author_dao.get(author.id)
if retrieved_author:
    print(f"Found author: {retrieved_author.name}")

# Check if an author exists
exists = author_dao.exists(author.id)
print(f"Author exists: {exists is not None}")

# List all authors (paginated)
all_authors = author_dao.list(limit=10, offset=0)
print(f"Total authors retrieved: {len(all_authors)}")

# List posts by filter (e.g., only published posts)
published_posts = post_dao.list_by(published=1, limit=50)
print(f"Published posts: {len(published_posts)}")

# List posts by specific author
author_posts = post_dao.list_by(author_id=author.id)
print(f"{author.name} has {len(author_posts)} posts")

# List posts ordered by creation date (newest first)
recent_posts = post_dao.list_by_order_by(
    Post.created_at.desc(),
    published=1,
    limit=5
)
print(f"Recent published posts: {[p.title for p in recent_posts]}")

# ============================================================
# UPDATE Operations
# ============================================================

# Update a single field
updated_post = post_dao.update(post2.id, published=1)
if updated_post:
    print(f"Published post: {updated_post.title}")

# Update multiple fields
updated_author = author_dao.update(
    author.id,
    bio="Senior Full-stack Developer and Tech Writer",
    email="jane.doe.new@example.com"
)
if updated_author:
    print(f"Updated author bio: {updated_author.bio}")

# ============================================================
# UPSERT Operations
# ============================================================

# Upsert - Update existing or create new
post3 = post_dao.upsert(
    999,  # If this ID doesn't exist, it will be created
    title="Database Design Principles",
    content="Good database design is crucial...",
    author_id=author.id,
    published=1
)
print(f"Upserted post: {post3.title}")

# ============================================================
# DELETE Operations
# ============================================================

# Delete a post
was_deleted = post_dao.delete(post3.id)
print(f"Post deleted: {was_deleted}")

# Try to delete non-existent record
was_deleted = post_dao.delete(99999)
print(f"Non-existent post deleted: {was_deleted}")  # False
```

### Example 3: Fire-and-Forget Background Operations

```python
from concurrent.futures import Future, as_completed

# ============================================================
# Asynchronous Operations (Fire-and-Forget)
# ============================================================

# Create multiple authors in the background
futures: List[Future[Author]] = []

authors_data = [
    {"name": "John Smith", "email": "john@example.com"},
    {"name": "Alice Johnson", "email": "alice@example.com"},
    {"name": "Bob Williams", "email": "bob@example.com"},
]

for data in authors_data:
    future = author_dao.create_ff(**data)
    futures.append(future)

# Continue with other work while authors are being created...
print("Authors are being created in the background...")

# Collect results when needed
for future in as_completed(futures):
    author = future.result()
    print(f"Background task completed: Created {author.name}")

# Fire-and-forget update
update_future = post_dao.update_ff(post1.id, title="Introduction to Python 3.12")
# Don't wait for result, continue immediately

# Fire-and-forget delete
delete_future = post_dao.delete_ff(post2.id)
# Get result later if needed
was_deleted = delete_future.result()
```

### Example 4: Custom Complex Queries

```python
from sqlalchemy import func, and_, or_

# ============================================================
# Custom Queries with run_custom
# ============================================================

def get_author_with_post_count(session: Session, author_id: int) -> Optional[tuple]:
    """Get author with their post count."""
    result = session.query(
        Author,
        func.count(Post.id).label('post_count')
    ).outerjoin(
        Post
    ).filter(
        Author.id == author_id
    ).group_by(
        Author.id
    ).first()
    
    if result:
        author, count = result
        session.expunge(author)  # Always expunge!
        return (author, count)
    return None

# Use the custom query
result = author_dao.run_custom(
    lambda session: get_author_with_post_count(session, author.id)
)
if result:
    author_obj, post_count = result
    print(f"{author_obj.name} has {post_count} posts")


def search_posts_by_title(session: Session, search_term: str) -> List[Post]:
    """Search posts by title (case-insensitive)."""
    posts = session.query(Post).filter(
        Post.title.ilike(f"%{search_term}%")
    ).all()
    
    for post in posts:
        session.expunge(post)
    return posts

# Search for posts
search_results = post_dao.run_custom(
    lambda session: search_posts_by_title(session, "python")
)
print(f"Found {len(search_results)} posts matching 'python'")


def get_recent_authors_with_published_posts(
    session: Session, 
    days: int = 30
) -> List[Author]:
    """Get authors who published posts in the last N days."""
    from datetime import datetime, timedelta
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    authors = session.query(Author).join(
        Post
    ).filter(
        and_(
            Post.published == 1,
            Post.created_at >= cutoff_date
        )
    ).distinct().all()
    
    for author in authors:
        session.expunge(author)
    return authors

# Get active authors
active_authors = author_dao.run_custom(
    lambda session: get_recent_authors_with_published_posts(session, days=7)
)
print(f"Active authors (last 7 days): {[a.name for a in active_authors]}")
```

### Example 5: Working with Relationships

```python
# ============================================================
# Handling Related Data
# ============================================================

def get_author_with_posts(session: Session, author_id: int) -> Optional[Author]:
    """Get author with all their posts eagerly loaded."""
    from sqlalchemy.orm import joinedload
    
    author = session.query(Author).options(
        joinedload(Author.posts)
    ).filter(
        Author.id == author_id
    ).first()
    
    if author:
        # Expunge the author and all loaded posts
        session.expunge(author)
        for post in author.posts:
            session.expunge(post)
    
    return author

# Get author with all posts in one query (avoiding N+1)
author_with_posts = author_dao.run_custom(
    lambda session: get_author_with_posts(session, author.id)
)

if author_with_posts:
    print(f"{author_with_posts.name} has posts:")
    for post in author_with_posts.posts:
        status = "Published" if post.published else "Draft"
        print(f"  - {post.title} ({status})")


def get_posts_with_author_info(
    session: Session, 
    published_only: bool = True
) -> List[tuple]:
    """Get posts with author information as tuples."""
    query = session.query(
        Post.id,
        Post.title,
        Post.created_at,
        Author.name.label('author_name'),
        Author.email.label('author_email')
    ).join(Author)
    
    if published_only:
        query = query.filter(Post.published == 1)
    
    results = query.all()
    return results

# Get posts with author info (efficient - only needed columns)
posts_info = post_dao.run_custom(
    lambda session: get_posts_with_author_info(session)
)

for post_id, title, created, author_name, author_email in posts_info:
    print(f"{title} by {author_name} ({created.strftime('%Y-%m-%d')})")
```

### Example 6: Bulk Operations and Transactions

```python
# ============================================================
# Bulk Operations
# ============================================================

from datetime import datetime

def bulk_create_posts(session: Session, posts_data: List[dict]) -> List[Post]:
    """Create multiple posts in a single transaction."""
    posts = []
    for data in posts_data:
        post = Post(**data)
        session.add(post)
        posts.append(post)
    
    session.flush()
    
    for post in posts:
        session.refresh(post)
        session.expunge(post)
    
    return posts

# Create multiple posts at once
bulk_posts_data = [
    {
        "title": f"Post {i}",
        "content": f"Content for post {i}",
        "author_id": author.id,
        "published": 1
    }
    for i in range(1, 6)
]

created_posts = post_dao.run_custom(
    lambda session: bulk_create_posts(session, bulk_posts_data)
)
print(f"Bulk created {len(created_posts)} posts")


def bulk_publish_drafts(session: Session, author_id: int) -> int:
    """Publish all draft posts for an author."""
    count = session.query(Post).filter(
        and_(
            Post.author_id == author_id,
            Post.published == 0
        )
    ).update(
        {"published": 1, "updated_at": datetime.utcnow()},
        synchronize_session=False
    )
    session.flush()
    return count

# Publish all drafts
published_count = post_dao.run_custom(
    lambda session: bulk_publish_drafts(session, author.id)
)
print(f"Published {published_count} draft posts")
```

### Example 7: Error Handling and Edge Cases

```python
# ============================================================
# Error Handling
# ============================================================

# Handle non-existent records
user = author_dao.get(99999)
if user is None:
    print("Author not found")

# Handle update of non-existent record
updated = author_dao.update(99999, name="Ghost Author")
if updated is None:
    print("Cannot update non-existent author")

# Safe delete
if author_dao.exists(some_id):
    author_dao.delete(some_id)
else:
    print("Author doesn't exist, nothing to delete")

# Custom query with error handling
def safe_get_author(session: Session, author_id: int) -> Optional[Author]:
    try:
        author = session.query(Author).filter(Author.id == author_id).first()
        if author:
            session.expunge(author)
        return author
    except Exception as e:
        print(f"Error fetching author: {e}")
        return None

result = author_dao.run_custom(
    lambda session: safe_get_author(session, author.id)
)
```

### Example 8: Working with Async Code

```python
import asyncio

async def create_authors_async():
    """Example of using the DAO in async context."""
    async def create_author_wrapper(name: str, email: str) -> Author:
        # Run the synchronous DAO method in a thread to avoid blocking the event loop
        return await asyncio.to_thread(author_dao.create, name=name, email=email)

    # Create multiple authors concurrently
    tasks = [
        create_author_wrapper(f"Author {i}", f"author{i}@example.com")
        for i in range(1, 4)
    ]
    return await asyncio.gather(*tasks)

# Run in async context
# authors = asyncio.run(create_authors_async())
```

### Best Practices When Using the DAO

1. **Always close DAOs when done** (especially in long-running applications):
   ```python
   try:
       # Use DAO
       result = author_dao.get(1)
   finally:
       author_dao.close()
   ```

2. **Reuse DAO instances** instead of creating new ones for each operation:
   ```python
   # Good - reuse
   dao = AuthorDAO(database_name="mydb")
   author1 = dao.get(1)
   author2 = dao.get(2)
   
   # Avoid - creates new connection pool each time
   author1 = AuthorDAO(database_name="mydb").get(1)
   author2 = AuthorDAO(database_name="mydb").get(2)
   ```

3. **Remember to expunge in custom queries**:
   ```python
   def custom_query(session: Session) -> List[Author]:
       authors = session.query(Author).all()
       for author in authors:
           session.expunge(author)  # Critical!
       return authors
   ```

4. **Use fire-and-forget for non-critical writes**:
   ```python
   # Log entry creation doesn't need to block
   log_future = log_dao.create_ff(
       message="User logged in",
       timestamp=datetime.utcnow()
   )
   # Continue immediately
   ```

5. **Handle None returns from get/update**:
   ```python
   author = author_dao.get(author_id)
   if author is None:
       raise ValueError(f"Author {author_id} not found")
   ```

---

## Conclusion: Focus on Your Logic, Not the Plumbing

SQLAlchemy is a masterpiece of software engineering—powerful and flexible. But that power demands expertise to use safely and efficiently. The Data Access Object we've built creates a **layer of safety and sanity** over SQLAlchemy's complexity.

### What We've Accomplished

The DAO pattern provides:

✅ **Automatic Session Management** – No more `DetachedInstanceError` or resource leaks  
✅ **Built-in Connection Pooling** – Production-ready connection management  
✅ **Type Safety** – Full generic type support  
✅ **Consistent API** – Simple, predictable CRUD operations  
✅ **Fire-and-Forget Operations** – Optional async without full conversion  
✅ **Flexible Extensibility** – Custom queries via `run_custom`  
✅ **Performance by Default** – Best practices baked in  

### The Philosophy

This DAO handles the messy plumbing—session management, boilerplate, performance tuning, and the async divide—so you can focus on **your application's business logic**.

Stop fighting the framework. Start building features.

---

## Additional Resources

For the complete implementation, see [`data_access_object.py`](./data_access_object.py).

### Key Takeaways

1. **Sessions are Stateful, Apps are Stateless** – Bridge the gap with abstraction
2. **Expunge Everything** – Return detached objects to avoid errors
3. **Embrace Convention** – Make the easy way the fast way
4. **Provide Escape Hatches** – Use `run_custom` when needed
5. **Thread Pools > Full Async** – Fire-and-forget is pragmatic

The DAO pattern transforms SQLAlchemy from a powerful but complex tool into a **safe, productive, and maintainable** data access layer.

---

 
> This document was initially drafted with the assistance of AI and then reviewed and edited by a human.

