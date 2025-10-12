from typing import List, Tuple

# Yes, I'm a typing freak. But you know what's even better than type hints?
# Dictionaries that yell at you when they change. Let's build that.
# 🎯 Import the star of the show
from observable_dict import ObservableDict


# 👂 Our listener: one callback to rule them all
def on_state_change(operation: str, items: List[Tuple[str, str]]):
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
    # .update() = one notification for multiple changes
    task_states.update({"task_alpha": "PENDING", "task_beta": "IDLE"})
    print("\n--- Starting task_alpha ---\n")
    # Direct assignment = instant ping
    task_states["task_alpha"] = "IN_PROGRESS"
    print("\n--- task_beta hits an error ---\n")
    task_states["task_beta"] = "ERROR"
    print("\n--- Deleting task_alpha ---\n")
    # Deletion? Yep, we hear that too
    del task_states["task_alpha"]
