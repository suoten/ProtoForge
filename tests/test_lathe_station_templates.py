from protoforge.core.simulators import get_device_simulator
from protoforge.core.template import TemplateManager


def test_mtconnect_lathe_station_templates_are_available():
    tm = TemplateManager()
    tm.load_builtin_templates()

    rough = tm.get_template("mtconnect_lathe_rough")
    semi = tm.get_template("mtconnect_lathe_semi_finish")
    finish = tm.get_template("mtconnect_lathe_finish")

    assert rough.name == "MTConnect车床 粗加工工位"
    assert semi.name == "MTConnect车床 半精加工工位"
    assert finish.name == "MTConnect车床 精加工工位"

    assert rough.protocol_config["device_uuid"] == "mtc-lathe-rough-001"
    assert semi.protocol_config["device_uuid"] == "mtc-lathe-semi-finish-001"
    assert finish.protocol_config["device_uuid"] == "mtc-lathe-finish-001"
    assert len(rough.points) == len(semi.points) == len(finish.points)
    assert "工位" in rough.tags
    assert "粗加工" in rough.tags
    assert "半精加工" in semi.tags
    assert "精加工" in finish.tags


def test_lathe_station_simulators_force_single_process():
    cases = [
        ("mtconnect_lathe_rough", "rough"),
        ("mtconnect_lathe_semi_finish", "semi_finish"),
        ("mtconnect_lathe_finish", "finish"),
    ]

    for template_id, process in cases:
        simulator = get_device_simulator(
            template_id,
            {"process_mode": "process_flow", "process": "rough"},
        )

        assert simulator is not None
        assert simulator._process_mode == "single_process"
        assert simulator._process == process
