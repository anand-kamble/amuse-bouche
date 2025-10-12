from collections.abc import ItemsView, Iterable, KeysView, Mapping, ValuesView
from typing import Any, Callable, Dict, Optional, Tuple, TypeVar, cast

K = TypeVar("K")
V = TypeVar("V")


class ObservableDict(Dict[K, V]):
    """An observable dictionary that provides change notifications for mutations.

    This class extends Python's built-in `dict` and provides notification capabilities
    for dictionary mutations. The callback signature mirrors `ObservableList`:
    `on_change(operation, items)`.

    **Important:** The callback function is called with best-effort error handling. If the callback
    raises an exception, it will be silently ignored to prevent disrupting the dictionary operations.

    ## Type Parameters

    - **K**: The type of keys stored in the dictionary
    - **V**: The type of values stored in the dictionary

    ## Inheritance

    - `dict`: Python's built-in dictionary type
    - `typing.Generic`: For generic type support

    ## Callback Signature

    The `on_change` callback receives two parameters:

    - **operation** (`str`): Describes the mutation type: `"set"`, `"update"`, `"pop"`,
      `"popitem"`, `"clear"`, `"delitem"`, or `"setdefault"`
    - **items** (`list` of `tuple`s): List of `(key, value)` tuples relevant to the operation

    ## Example Usage

    ```python
    def on_change(operation: str, items: list) -> None:
        print(f"Operation: {operation}, Items: {items}")

    # Create an observable dictionary
    obs_dict = ObservableDict[str, int]({"a": 1, "b": 2}, on_change=on_change)

    # Mutations will trigger notifications
    obs_dict["c"] = 3  # Triggers: operation="set", items=[("c", 3)]
    obs_dict.update({"d": 4, "e": 5})  # Triggers: operation="update", items=[("d", 4), ("e", 5)]
    obs_dict.pop("a")  # Triggers: operation="pop", items=[("a", 1)]
    ```

    ## Thread Safety

    This class is not thread-safe. If used in multi-threaded environments, external
    synchronization is required.

    ## Summary

    ObservableDict provides a powerful foundation for reactive programming.
    By extending Python's built-in dictionary with change notifications, it enables:

    - **Data Synchronization**: Automatic updates across different parts of the system
    - **Audit Trails**: Complete tracking of data modifications
    - **Debugging**: Easy monitoring of data changes during development

    The class maintains full compatibility with Python's dict interface while adding
    the observability layer that makes the data management system
    both powerful and maintainable.

    ## See Also

    - `ObservableList`: Similar observable pattern for lists
    """

    def __init__(
        self,
        initial: Optional[Mapping[K, V] | Iterable[Tuple[K, V]]] = None,
        on_change: Optional[Callable[[str, list[Tuple[K, V]]], None]] = None,
        **kwargs: V,
    ) -> None:
        """Initialize an ObservableDict with optional initial data and change callback.

        ## Args

        - **initial**: Optional initial data to populate the dictionary. Can be:
            - A mapping (dict-like object) that will be converted to key-value pairs
            - An iterable of (key, value) tuples
            - None for an empty dictionary
        - **on_change**: Optional callback function that will be called on mutations.
            The callback signature is: `on_change(operation: str, items: list[Tuple[K, V]]) -> None`
            where:
            - `operation` describes the type of mutation performed
            - `items` contains the affected key-value pairs
        - **kwargs**: Additional key-value pairs to initialize the dictionary with.
            These are processed after the `initial` parameter.

        ## Raises

        - **TypeError**: If the callback function has an incompatible signature
        - **ValueError**: If initial data contains invalid key-value pairs
        """
        if initial is None:
            super().__init__(**kwargs)
        else:
            super().__init__(initial, **kwargs)
        self._on_change: Optional[Callable[[str, list[Tuple[K, V]]], None]] = on_change

    def set_on_change(
        self, on_change: Optional[Callable[[str, list[Tuple[K, V]]], None]]
    ) -> None:
        """Set or update the change notification callback.

        ## Args

        - **on_change**: The callback function to call on mutations, or None to disable notifications.
            The callback signature is: `on_change(operation: str, items: list[Tuple[K, V]]) -> None`
            where:
            - `operation` is one of: "set", "update", "pop", "popitem", "clear", "delitem", "setdefault"
            - `items` is a list of (key, value) tuples affected by the operation

        ## Note

        Setting the callback to None will disable change notifications. The callback
        is called with best-effort error handling - exceptions in the callback are
        silently ignored to prevent disrupting dictionary operations.

        This method can be called multiple times to change the callback during
        the dictionary's lifetime.

        ## Example

        ```python
        obs_dict = ObservableDict[str, int]()

        def my_callback(operation: str, items: list) -> None:
            print(f"Dictionary changed: {operation} -> {items}")

        # Set the callback
        obs_dict.set_on_change(my_callback)
        obs_dict["key"] = 42  # Will trigger callback

        # Change to a different callback
        def another_callback(operation: str, items: list) -> None:
            print(f"Different handler: {operation}")

        obs_dict.set_on_change(another_callback)

        # Disable notifications
        obs_dict.set_on_change(None)
        obs_dict["key2"] = 100  # No callback triggered
        ```
        """
        self._on_change = on_change

    def _notify(self, operation: str, items: list[Tuple[K, V]]) -> None:
        """Internal method to notify the callback of dictionary changes.

        ## Args

        - **operation**: The type of operation that was performed. Must be one of:
            "set", "update", "pop", "popitem", "clear", "delitem", "setdefault"
        - **items**: List of (key, value) tuples affected by the operation

        ## Note

        This method is called internally by mutating operations. Exceptions
        in the callback are silently ignored to prevent disrupting dictionary
        operations. This ensures that dictionary operations always complete
        successfully even if the callback fails.

        The method performs a quick check for the presence of a callback
        before attempting to call it, optimizing performance when no callback
        is set.

        > **Warning**: This is an internal method and should not be called directly by
        > external code. Use the public mutating methods instead.
        """
        if self._on_change:
            try:
                self._on_change(operation, items)
            except Exception:
                pass

    # Mutating operations
    def __setitem__(self, key: K, value: V) -> None:  # type: ignore[override]
        """Set a key-value pair in the dictionary.

        ## Args

        - **key**: The key to set
        - **value**: The value to associate with the key

        ## Note

        This method triggers a "set" notification with the key-value pair.
        Both new keys and updates to existing keys will trigger notifications.

        ## Example

        ```python
        obs_dict = ObservableDict[str, int](on_change=my_callback)
        obs_dict["new_key"] = 42  # Triggers: operation="set", items=[("new_key", 42)]
        obs_dict["existing_key"] = 100  # Triggers: operation="set", items=[("existing_key", 100)]
        ```
        """
        super().__setitem__(key, value)
        self._notify("set", [(key, value)])

    def update(self, other: Any = None, **kwargs: V) -> None:  # type: ignore[override]
        """Update the dictionary with elements from another mapping or iterable.

        ## Args

        - **other**: Optional mapping or iterable of key-value pairs to update with.
            Can be:
            - A mapping (dict-like object) that will be converted to key-value pairs
            - An iterable of (key, value) tuples
            - None to skip this parameter
            - Any object that supports the mapping protocol
        - **kwargs**: Additional key-value pairs to update with

        ## Note

        This method triggers a single "update" notification with all changed items.
        If both `other` and `kwargs` are provided, all changes are included in one notification.

        ## Example

        ```python
        obs_dict = ObservableDict[str, int]({"a": 1}, on_change=my_callback)

        # Update with a mapping
        obs_dict.update({"b": 2, "c": 3})  # Triggers: operation="update", items=[("b", 2), ("c", 3)]

        # Update with keyword arguments
        obs_dict.update(d=4, e=5)  # Triggers: operation="update", items=[("d", 4), ("e", 5)]

        # Update with both
        obs_dict.update({"f": 6}, g=7)  # Triggers: operation="update", items=[("f", 6), ("g", 7)]
        ```
        """
        changed: list[Tuple[K, V]] = []
        if other is not None:
            if isinstance(other, Mapping):
                pairs_from_mapping: Iterable[Tuple[K, V]] = cast(
                    Iterable[Tuple[K, V]], other.items()
                )
                changed.extend(self._assign_pairs(pairs_from_mapping))
            else:
                changed.extend(self._assign_pairs(other))
        if kwargs:
            for k, v in kwargs.items():
                key_as_k: K = cast(K, k)
                super().__setitem__(key_as_k, v)
                changed.append((key_as_k, v))
        if changed:
            self._notify("update", changed)

    # -------------------- Internal helpers --------------------
    def _assign_pairs(self, pairs: Iterable[Tuple[K, V]]) -> list[Tuple[K, V]]:
        """Assign key/value pairs to self and return the list of changed pairs.

        This helper is separated to aid the type checker so that union types from
        Mapping | Iterable branches don't pollute loop variable inference.

        ## Args

        - **pairs**: Iterable of (key, value) tuples to assign to the dictionary

        ## Returns

        List of (key, value) tuples that were assigned. This includes all
        pairs that were processed, regardless of whether they replaced
        existing values or added new ones.

        ## Note

        This is an internal helper method used by the `update()` method to
        handle type checking for different input types. It performs the actual
        assignment operations and tracks what was changed for notification purposes.

        The method directly modifies the dictionary using the parent class's
        `__setitem__` method, bypassing the observable notification system
        to avoid duplicate notifications.

        > **Warning**: This is an internal method and should not be called directly by
        > external code. Use the public `update()` method instead.
        """
        changed: list[Tuple[K, V]] = []
        for key, value in pairs:
            super().__setitem__(key, value)
            changed.append((key, value))
        return changed

    def setdefault(self, key: K, default: Optional[V] = None) -> V:  # type: ignore[override]
        """Set a key to a default value if the key is not already in the dictionary.

        ## Args

        - **key**: The key to set
        - **default**: The default value to use if the key is not present. If None,
            the default value will be None (cast to type V)

        ## Returns

        The value of the key (existing value if key was present, default value if newly set)

        ## Note

        This method only triggers a "setdefault" notification if the key was not
        already present in the dictionary. If the key exists, no notification is sent.

        ## Example

        ```python
        obs_dict = ObservableDict[str, int]({"a": 1}, on_change=my_callback)

        # Key exists - no notification
        value = obs_dict.setdefault("a", 99)  # Returns 1, no notification

        # Key doesn't exist - triggers notification
        value = obs_dict.setdefault("b", 42)  # Returns 42, triggers: operation="setdefault", items=[("b", 42)]
        ```
        """
        if key in self:
            return self[key]
        value: V = default if default is not None else cast(V, None)
        super().__setitem__(key, value)
        self._notify("setdefault", [(key, value)])
        return value

    def pop(self, key: K, default: Optional[V] = None) -> V:  # type: ignore[override]
        """Remove and return a value from the dictionary.

        ## Args

        - **key**: The key to remove
        - **default**: Optional default value to return if the key is not found.
            If None and key is not found, raises KeyError

        ## Returns

        The value associated with the key, or the default value if key not found

        ## Raises

        - **KeyError**: If the key is not found and no default value is provided

        ## Note

        This method triggers a "pop" notification only if the key was present
        and removed. If the key is not found and a default is returned, no
        notification is sent.

        ## Example

        ```python
        obs_dict = ObservableDict[str, int]({"a": 1, "b": 2}, on_change=my_callback)

        # Key exists - triggers notification
        value = obs_dict.pop("a")  # Returns 1, triggers: operation="pop", items=[("a", 1)]

        # Key doesn't exist with default - no notification
        value = obs_dict.pop("c", 99)  # Returns 99, no notification

        # Key doesn't exist without default - raises KeyError
        value = obs_dict.pop("d")  # Raises KeyError
        ```
        """
        if key in self:
            value = super().pop(key)
            self._notify("pop", [(key, value)])
            return value
        if default is not None:
            return default
        # Mirror dict.pop KeyError when no default provided
        return super().pop(key)  # type: ignore[return-value]

    def popitem(self) -> Tuple[K, V]:  # type: ignore[override]
        """Remove and return an arbitrary (key, value) pair from the dictionary.

        ## Returns

        A tuple containing the removed key-value pair

        ## Raises

        - **KeyError**: If the dictionary is empty

        ## Note

        This method triggers a "popitem" notification with the removed key-value pair.
        The order of removal is not guaranteed (depends on Python's dict implementation).

        ## Example

        ```python
        obs_dict = ObservableDict[str, int]({"a": 1, "b": 2}, on_change=my_callback)

        # Remove arbitrary item - triggers notification
        key, value = obs_dict.popitem()  # Triggers: operation="popitem", items=[(key, value)]
        print(f"Removed: {key} = {value}")
        ```
        """
        item = super().popitem()
        self._notify("popitem", [item])
        return item

    def clear(self) -> None:  # type: ignore[override]
        """Remove all items from the dictionary.

        ## Note

        This method triggers a "clear" notification with all items that were
        removed. If the dictionary is already empty, no notification is sent.

        ## Example

        ```python
        obs_dict = ObservableDict[str, int]({"a": 1, "b": 2, "c": 3}, on_change=my_callback)

        # Clear all items - triggers notification
        obs_dict.clear()  # Triggers: operation="clear", items=[("a", 1), ("b", 2), ("c", 3)]

        # Clear empty dictionary - no notification
        obs_dict.clear()  # No notification
        ```
        """
        if not self:
            super().clear()
            return
        removed_items = list(self.items())
        super().clear()
        self._notify("clear", removed_items)

    def __delitem__(self, key: K) -> None:  # type: ignore[override]
        """Delete a key from the dictionary.

        ## Args

        - **key**: The key to delete

        ## Raises

        - **KeyError**: If the key is not found

        ## Note

        This method triggers a "delitem" notification with the deleted key-value pair.
        The value is captured before deletion for the notification.

        ## Example

        ```python
        obs_dict = ObservableDict[str, int]({"a": 1, "b": 2}, on_change=my_callback)

        # Delete existing key - triggers notification
        del obs_dict["a"]  # Triggers: operation="delitem", items=[("a", 1)]

        # Delete non-existent key - raises KeyError
        del obs_dict["c"]  # Raises KeyError
        ```
        """
        value = self[key]
        super().__delitem__(key)
        self._notify("delitem", [(key, value)])

    # Convenience helpers
    def copy(self) -> "ObservableDict[K, V]":  # type: ignore[override]
        """Create a shallow copy of the ObservableDict.

        ## Returns

        A new `ObservableDict` instance with the same key-value pairs but no callback

        ## Note

        The returned copy will not have the change notification callback set.
        You can set a new callback using `set_on_change()` if needed.

        This method creates a completely independent copy that shares no state
        with the original dictionary, except for the key-value pairs themselves.
        Changes to the copy will not affect the original and vice versa.

        ## Example

        ```python
        original = ObservableDict[str, int]({"a": 1, "b": 2}, on_change=my_callback)
        copy_dict = original.copy()  # No callback set
        copy_dict.set_on_change(another_callback)  # Set new callback

        # Changes are independent
        original["c"] = 3  # Only original's callback is triggered
        copy_dict["d"] = 4  # Only copy's callback is triggered
        ```
        """
        return ObservableDict(self.items())

    def items(self) -> ItemsView[K, V]:  # type: ignore[override]
        """Return a view of the dictionary's key-value pairs.

        ## Returns

        A view object that displays a list of the dictionary's key-value pairs

        ## Note

        This is a non-mutating operation and does not trigger change notifications.
        The returned view is dynamic and reflects changes to the dictionary.
        """
        return super().items()

    def keys(self) -> KeysView[K]:  # type: ignore[override]
        """Return a view of the dictionary's keys.

        ## Returns

        A view object that displays a list of the dictionary's keys

        ## Note

        This is a non-mutating operation and does not trigger change notifications.
        The returned view is dynamic and reflects changes to the dictionary.
        """
        return super().keys()

    def values(self) -> ValuesView[V]:  # type: ignore[override]
        """Return a view of the dictionary's values.

        ## Returns

        A view object that displays a list of the dictionary's values

        ## Note

        This is a non-mutating operation and does not trigger change notifications.
        The returned view is dynamic and reflects changes to the dictionary.
        """
        return super().values()

    def to_dict(self) -> Dict[K, V]:
        """Convert the ObservableDict to a regular Python dictionary.

        ## Returns

        A new regular `dict` with the same key-value pairs

        ## Note

        This is a non-mutating operation and does not trigger change notifications.
        The returned dictionary is a shallow copy and independent of the original.

        This method is particularly useful when you need to pass the dictionary
        to functions that expect a regular Python dict, or when serializing
        the data for storage or transmission.

        ## Example

        ```python
        obs_dict = ObservableDict[str, int]({"a": 1, "b": 2}, on_change=my_callback)
        regular_dict = obs_dict.to_dict()  # Returns dict[str, int]
        print(type(regular_dict))  # <class 'dict'>

        # Use with functions that expect regular dict
        import json
        json_str = json.dumps(obs_dict.to_dict())
        ```
        """
        return dict(self)


__all__ = ["ObservableDict"]