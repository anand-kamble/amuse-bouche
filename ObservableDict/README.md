# How I Built a Dictionary That Shouts: A Simple Observer Story at Liebre.ai

> “How a tricky problem with AI agents led me to build a self-aware data structure, rediscover a classic design pattern, and appreciate the elegance of Python’s magic methods.”

[View on Medium](https://medium.com/@anand-kamble/how-i-built-a-dictionary-that-shouts-a-simple-observer-story-at-liebre-ai-f2744c8cdf05)

## The Shared State Headache

Here at Liebre.ai, building internal frameworks for AI Agents feels a bit like conducting an orchestra of digital colleagues. Each agent is a specialist with its own unique job. We have a “Data Fetcher” agent that scours sources for information, a “Language Processor” that makes sense of it all, and a “Decision Maker” that charts the next course of action. It’s a dynamic, exciting, and sometimes wonderfully chaotic environment.

Making these agents individually smart is one challenge. But the real magic and the real headache is getting them to share information and react to changes effectively.

A few weeks ago, I hit a classic roadblock. We needed a central place to store the status of multiple, long-running tasks. A simple Python dictionary seemed perfect for this “shared state.” It might look something like this:
```python
task_states = {
    "task_alpha": {"status": "PENDING", "progress": 0},
    "task_beta": {"status": "IDLE", "progress": 0},
}
```
The problem was, several different agents needed to know the moment any of this data changed:

*   A `Logger` agent needed to write every status change to a log file.
*   A `Dashboard` agent needed to update a real-time UI with the latest progress.
*   An `Alerting` agent needed to watch for an `ERROR` status and send a notification.

How could we manage this shared dictionary and inform all these other agents without creating a tangled mess? This wasn’t just an AI problem; it was a fundamental software design problem. The journey to solve it led me from a brittle, complex solution to a surprisingly simple and elegant data structure.


## Part 1: The Naive Approach and the Spaghetti Monster
My first instinct was the most direct one. I could create a `StateManager` class that would wrap the dictionary. Any agent wanting to change the state would have to call a method on this manager. The manager, in turn, would be responsible for notifying everyone else.

It would look something like this:

```python
# The "Don't Do This" Version
class StateManager:
    def __init__(self, logger, dashboard, alerter):
        self.logger = logger
        self.dashboard = dashboard
        self.alerter = alerter
        self.task_states = {}

    def set_state(self, task_id, key, value):
        if task_id not in self.task_states:
            self.task_states[task_id] = {}
        
        self.task_states[task_id][key] = value
        print(f"--- State changed for {task_id}: {key} = {value} ---")
        
        # Direct, tightly-coupled calls
        if key == 'status':
            self.logger.log(task_id, value)
            self.alerter.check(task_id, value)
        if key == 'progress':
            self.dashboard.update(task_id, value)

# --- Dummy classes for the example ---
class Logger:
    def log(self, task_id, status): pass
class Dashboard:
    def update(self, task_id, progress): pass
class Alerter:
    def check(self, task_id, status): pass
````

This works, but it feels… fragile. It’s like a micromanager who has to approve every change and then personally walk over to tell everyone what happened. What happens next week when our team at Liebre.ai decides we also need an `AnalyticsCollector` agent to listen for progress changes? We'd have to go back, open up the `StateManager` class, add a new parameter to its `__init__`, and add more `if` statements inside `set_state`.

This creates what I affectionately call a “Spaghetti Monster.” The `StateManager` is now **tightly coupled** to the other agents. It knows too much about them. This design is brittle and violates a key software design principle: the **Open/Closed Principle**, which states that software entities should be open for extension but closed for modification. Our `StateManager` is wide open for constant modification, and that's a recipe for bugs.

## Part 2: The ‘Aha\!’ Moment, What if the Dictionary Could Shout?

I took a step back. The core problem was that the `StateManager` was doing too much. It was managing the data *and* managing the notifications.

What if we inverted that control? What if the data structure itself could announce changes?

Instead of using a plain `dict` and wrapping it in a manager, what if I could create a *new kind of dictionary* that would automatically shout, "Hey, someone just set the key 'status' to 'COMPLETED'\!" whenever it was modified?

This was the breakthrough (for me 🙂). The responsibility for notification shouldn’t be in some external manager; it should be an intrinsic property of the data structure itself. This led me to create a new class, which I called `ObservableDict`. The goal was simple: it should behave exactly like a normal Python dictionary, but with a secret superpower.

## Part 3: Building the `ObservableDict` by Hijacking the Dictionary

The plan was to create a class that inherits from Python’s built-in `dict` and then override all the methods that change its contents. This is where the magic happens.

### Step 1: Inheritance and the Callback

First, the class definition is simple. By inheriting from `dict`, we get all the standard dictionary functionality (like `get`, `keys`, `items`, etc.) for free.

Then, in the `__init__` method, we accept an optional `on_change` function. This function, often called a "callback," is the listener we'll notify whenever a change occurs.

```python
from typing import Callable, Dict, Optional, Tuple, TypeVar

# Yes, I am a typing freak
K = TypeVar("K")
V = TypeVar("V")


class ObservableDict(Dict[K, V]):
    def __init__(
        self,
        initial: Optional[dict] = None,
        on_change: Optional[Callable[[str, list], None]] = None,
    ):
        # Call the parent dict's initializer
        super().__init__(initial or {})
        # Store the callback function
        self._on_change = on_change
        
    def _notify(self, operation: str, items: list):
        """Internal method to call the callback if it exists."""
        if self._on_change:
            try:
                self._on_change(operation, items)
            except Exception:
                # Silently ignore errors in the callback
                pass
```

I also added a `_notify` helper method. This is the "shouting" mechanism. It checks if a callback function was provided and, if so, calls it with two crucial pieces of information:

  * `operation`: A string describing what kind of change happened (e.g., `"set"`, `"pop"`).
  * `items`: A list of the `(key, value)` pairs that were affected.

### Step 2: Overriding a Mutating Method

Now for the fun part. To detect changes, we need to intercept the operations that modify the dictionary. The most common one is setting a value using square brackets, which in Python is handled by the `__setitem__` magic method.

By overriding it, we can inject our notification logic.

```python
class ObservableDict(Dict[K, V]):
    #... (init and _notify methods from above)...
    def __setitem__(self, key: K, value: V):
        """Overrides the `d[key] = value` operation."""
        # First, let the original dictionary do its job.
        super().__setitem__(key, value)
        
        # Now, shout about what just happened!
        self._notify("set", [(key, value)])
```

This is so cool\! We’re not reinventing the wheel; we’re just adding a step. First, `super().__setitem__(key, value)` ensures the key and value are actually stored in the dictionary just like normal. Then, after the operation succeeds, we call `self._notify`.

I applied this same pattern to all the other methods that change the dictionary: `__delitem__`, `pop`, `update`, `clear`, and so on. Each override calls the `super()` method first and then calls `_notify` with the appropriate operation name and affected items.

Here’s the override for `pop` as another example:

```python
class ObservableDict(Dict[K, V]):
    #... (other methods)...
    def pop(self, key: K, default: Optional[V] = None) -> V:
        """Overrides the `d.pop(key)` operation."""
        if key in self:
            # We need to get the value *before* it's removed
            value = super().pop(key)
            self._notify("pop", [(key, value)])
            return value
        # If the key doesn't exist, behave like a normal dict
        if default is not None:
            return default
        raise KeyError(key)
```

By doing this for every mutating method, we create a data structure that is fully “observable.” It works just like a dictionary, but it leaves a trail of breadcrumbs for every change it undergoes.

## Part 4: Putting It All Together: A Mock AI Agent Scenario

Now, let’s solve our original problem using our shiny new `ObservableDict`. We'll create a shared dictionary for our task states and a single callback function to handle all notifications.

Here is the complete, runnable Python script (you can find the full source file on my GitHub here: [observable\_dict\_demo.py](https://github.com/anand-kamble/amuse-bouche/blob/main/ObservableDict/observable_dict_demo.py)).

```python
from typing import List, Tuple

# Yes, I'm a typing freak. But you know what's even better than type hints?
# Dictionaries that yell at you when they change. Let's build that.
# 🎯 Import the star of the show
from observable_dict import ObservableDict


# 👂 Our listener: one callback to rule them all
def on_state_change(operation: str, items: List]):
    """Catches every dict change and routes it like a boss."""
    print(f"Callback triggered! Operation: '{operation}', Items: {items}")

    # Smart routing: different keys, different actions
    for key, value in items:
        if key == "status" and value == "ERROR":
            print(f"  -> ALERT! Task has an error: {items}")
        if key == "status":
            print(f"  -> LOGGING: Status changed: {items}")
        if key == "progress":
            print(f"  -> DASHBOARD: Updating UI with progress: {items}")


# 🚀 Let's see it in action
if __name__ == "__main__":
    print("Starting AI Agent simulation at Liebre.ai...")
    # Wire up the dictionary with our callback
    task_states = ObservableDict(on_change=on_state_change)

    print("\n--- Setting initial state ---\n")
    #.update() = one notification for multiple changes
    task_states.update({"task_alpha": "PENDING", "task_beta": "IDLE"})
    
    print("\n--- Starting task_alpha ---\n")
    # Direct assignment = instant ping
    task_states["task_alpha"] = "IN_PROGRESS"
    
    print("\n--- task_beta hits an error ---\n")
    task_states["task_beta"] = "ERROR"
    
    print("\n--- Deleting task_alpha ---\n")
    # Deletion? Yep, we hear that too
    del task_states["task_alpha"]
```

When you run this script, you’ll see the following output:

```
Starting AI Agent simulation at Liebre.ai...

--- Setting initial state ---

Callback triggered! Operation: 'update', Items:

--- Starting task_alpha ---

Callback triggered! Operation: 'set', Items:

--- task_beta hits an error ---

Callback triggered! Operation: 'set', Items:

--- Deleting task_alpha ---

Callback triggered! Operation: 'delitem', Items:
```

It works perfectly\! We just use standard dictionary syntax, and our `on_state_change` function is automatically called with detailed information about every change. The dictionary itself is now the central publisher of events. This is the power of decoupled, event-driven design.

## Part 5: Standing on the Shoulders of Giants: Discovering the Observer Pattern

After I built this and saw how cleanly it solved our communication problem at Liebre.ai, I had that classic developer feeling: “This is too simple and elegant… someone must have thought of this before.”

Of course, they had.

A bit of research confirmed that I hadn’t invented a new wheel—I had rediscovered a classic. What I built is an implementation of the **Observer Design Pattern**. It’s one of the 23 foundational “Gang of Four” design patterns that have been a cornerstone of object-oriented design for decades.

The formal terminology maps perfectly to our solution:

  * **Subject (or Observable)**: This is the object being watched. In our example, the `ObservableDict` instance is the Subject. It maintains its own state and notifies observers when that state changes.
  * **Observer (or Subscriber)**: This is the object that watches the Subject. Our `on_state_change` function is the Observer. It registers with the Subject (via the `__init__` or `set_on_change` method) and receives updates.

This realization was incredibly validating. It showed that the logical steps I took to solve a practical problem led me to the same conclusion that seasoned software architects reached years ago. These patterns aren’t just academic exercises; they are battle-tested solutions to recurring problems. The journey of rediscovering one is often the best way to truly understand it.

If you want to dive deeper into the formal theory, I highly recommend checking out the excellent overview on(https://refactoring.guru/design-patterns/observer) or [Microsoft’s documentation](https://learn.microsoft.com/en-us/dotnet/standard/events/observer-design-pattern), which has a great explanation that’s conceptually universal.

## Conclusion: A Stepping Stone to the Reactive Universe

So, we faced a communication problem between our AI agents at Liebre.ai, rejected a tightly-coupled approach, and built a simple, reusable `ObservableDict` based on the classic Observer pattern. It's a powerful tool for synchronous, in-process state management.

But now for the crucial disclaimer: **This simple `ObservableDict` is a fantastic learning tool, but it's not a replacement for mature frameworks.** When the real world gets messy with asynchronous operations, complex streams of data, sophisticated error handling, and concurrency, we need to bring in the heavy artillery.

This is where **Reactive Programming** comes in.

Reactive programming is a programming paradigm that takes the core idea of the Observer pattern and supercharges it for the modern, asynchronous world. It’s built around the concept of asynchronous data streams (called **Observables**) that emit values, errors, or a completion signal over time.

Frameworks like **ReactiveX (Rx)** are implementations of this paradigm, often described as “the Observer pattern done right”. For us Pythonistas, the go-to library is **RxPy**. These frameworks give us superpowers that our simple dictionary doesn’t have.

To make the distinction clear, here’s a quick comparison:

| Feature | Our Simple `ObservableDict` | ReactiveX (`RxPy`) `Observable` | Why It Matters |
| :--- | :--- | :--- | :--- |
| **Notification Type** | A single `on_change` callback for data. | Three distinct channels: `on_next` (data), `on_error` (exceptions), `on_completed` (end of stream). | **Resilience & Clarity:** ReactiveX explicitly models the entire lifecycle of an asynchronous process. You know not only *what* data arrived, but also *if* the process failed or finished successfully. |
| **Data Flow** | Simple, direct push on every change. | A "stream" of data over time that can be transformed, filtered, and combined with powerful **operators**. | **Power & Expressiveness:** Instead of just receiving data, you can build a declarative pipeline to process it. `source.pipe(ops.filter(...), ops.map(...))` is far more readable and powerful than a giant `if/elif` block in a callback. |
| **Error Handling** | None in the callback. An error in the listener is silently ignored. | A dedicated `on_error` channel. Errors are treated as data, allowing for retry logic, fallbacks, and clean handling. | **Robustness:** In asynchronous systems, errors are normal. ReactiveX provides a structured way to handle them without `try/catch` blocks that don't work across async boundaries. |
| **Concurrency** | Synchronous. Runs on a single thread. | Managed via **Schedulers**. You can easily move work to background threads with operators like `subscribe_on` and `observe_on`. | **Performance & Responsiveness:** For I/O-bound or CPU-intensive tasks, you can prevent blocking the main thread, leading to more responsive applications. This is a huge advantage over the simple pattern. |

If this idea of event streams excites you, I highly recommend checking out the official(https://reactivex.io/) and, for my fellow Python developers, the excellent(https://github.com/ReactiveX/RxPY). Think of the Observer pattern as learning musical scales. ReactiveX is like learning to compose a full symphony.

You can find the complete source code for this tutorial here:
[ObservableDict](https://github.com/anand-kamble/amuse-bouche/tree/main/ObservableDict)

-----

*Disclosure: Drafted with an AI (Gemini 2.5 Pro) and human-edited for accuracy and tone.*

