from taskiq import InMemoryBroker

from atria.core.tasks.broker import make_broker


def test_make_broker_returns_inmemory_under_pytest(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "pytest")
    broker = make_broker("redis://localhost:6379/0", result_ttl=10)
    assert isinstance(broker, InMemoryBroker)


def test_make_broker_returns_redis_broker_otherwise(monkeypatch):
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    broker = make_broker("redis://localhost:6379/0", result_ttl=10)
    # ListQueueBroker, not InMemory
    assert not isinstance(broker, InMemoryBroker)
    assert broker.result_backend is not None
