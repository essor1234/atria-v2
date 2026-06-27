from atria.core.tasks.broker import broker
from atria.core.tasks.client import TaskIQClient
from atria.core.tasks.lifecycle import attach_task_client, make_task_client


def test_make_task_client_uses_singleton_broker():
    client = make_task_client("redis://localhost:6379/0", orphan_after=900)
    assert isinstance(client, TaskIQClient)
    assert client._broker is broker  # same singleton the task is registered on
    assert client._orphan_after == 900


def test_make_task_client_registers_task_on_broker():
    make_task_client("redis://localhost:6379/0", 1800)
    # Importing lifecycle imports tasks, registering the task on the singleton broker.
    assert broker.find_task("atria.core.tasks.tasks.run_background_subagent") is not None


def test_attach_task_client_sets_on_manager():
    calls = {}

    class _Mgr:
        def set_task_client(self, c):
            calls["client"] = c

    class _Reg:
        def get_subagent_manager(self):
            return _Mgr()

    sentinel = object()
    attach_task_client(_Reg(), sentinel)
    assert calls["client"] is sentinel


def test_attach_task_client_noop_when_client_none():
    class _Reg:
        def get_subagent_manager(self):
            raise AssertionError("should not be called when client is None")

    attach_task_client(_Reg(), None)  # must not raise
