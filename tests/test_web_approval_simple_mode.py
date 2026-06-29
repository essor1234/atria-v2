from types import SimpleNamespace

from atria.models.config import AppConfig
from atria.models.operation import Operation, OperationType
from atria.web.web_approval_manager import WebApprovalManager


def _manager_with(simple_mode: bool) -> WebApprovalManager:
    # Build without touching the real event loop / ws; we only exercise the
    # early-return path, which uses self.state only.
    mgr = WebApprovalManager.__new__(WebApprovalManager)
    mgr.ws_manager = SimpleNamespace(broadcast=lambda *a, **k: None)
    mgr.loop = None
    mgr.session_id = "test"
    cfg = AppConfig(simple_mode=simple_mode)
    mgr.state = SimpleNamespace(
        config_manager=SimpleNamespace(get_config=lambda: cfg),
        get_autonomy_level=lambda: "Manual",
    )
    return mgr


def _bash_op() -> Operation:
    return Operation(
        type=OperationType.BASH_EXECUTE,
        target="python /tmp/modules/warehouse/scripts/inventory.py receive",
        parameters={"command": "python /tmp/modules/warehouse/scripts/inventory.py receive"},
    )


def test_simple_mode_auto_approves_without_broadcast():
    mgr = _manager_with(simple_mode=True)
    result = mgr.request_approval(_bash_op(), preview="", command="x")
    assert result.approved is True
    assert result.choice == "approve"


def test_simple_mode_off_still_consults_autonomy_manual():
    # With Simple Mode off and Manual autonomy, the early return must NOT fire;
    # the helper reports disabled.
    mgr = _manager_with(simple_mode=False)
    assert mgr._simple_mode_enabled() is False
