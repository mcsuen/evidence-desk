"""Local coding agents, selected and bound independently for each task."""
from contextlib import contextmanager
from contextvars import ContextVar

current = ContextVar('pitr_agent_task', default=None)


@contextmanager
def task_scope(desk, task, fence=lambda: None):
    runtime = getattr(desk, 'agents', None)
    token = current.set((runtime, task, fence) if runtime and task.get('agent') else None)
    try:
        yield
    finally:
        current.reset(token)


def bind_task(desk, task, provider=None, model=None, reasoning=None, parent=None):
    runtime = getattr(desk, 'agents', None)
    if runtime:
        import copy
        if parent is not None:
            if parent.get('agent'):
                task['agent'] = copy.deepcopy(runtime._binding(parent))
        else:
            task['agent'] = runtime.selection(provider, model, reasoning)
    return task
