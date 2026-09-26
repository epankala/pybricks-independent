"""Behavior of hub/worker.py, simulated with fake pybricks modules."""

from pathlib import Path

from hubsim import Sim

from pybricks_independent import program

WORKER = Path(__file__).parent.parent / "hub" / "worker.py"


def simulate(until_ms=2000, debug=False, **world):
    source = WORKER.read_text()
    if debug:
        source = program.debug_source(source)
    return Sim(**world).run(WORKER, until_ms, source=source)


def drive_commands(sim):
    return [e[1:] for e in sim.events if e[1] in ("run", "stop")]


def test_motors_are_mirrored_so_plus_drives_forward():
    sim = simulate(until_ms=100)
    assert ("motor init", "A", "COUNTERCLOCKWISE") in [e[1:] for e in sim.events]
    assert ("motor init", "B", "CLOCKWISE") in [e[1:] for e in sim.events]


def test_buttons_drive_motors_while_held():
    sim = simulate(buttons=[(0, set()), (100, {"LEFT_PLUS"}), (300, {"LEFT_PLUS", "RIGHT_MINUS"}), (500, set())])
    commands = drive_commands(sim)
    start = commands.index(("run", "A", 300))  # first gear: 30 % of max speed
    assert commands[start:] == [
        ("run", "A", 300),
        ("stop", "B"),
        ("run", "A", 300),
        ("run", "B", -300),
        ("stop", "A"),
        ("stop", "B"),
    ]


def test_opposite_buttons_cancel_out():
    sim = simulate(buttons=[(0, {"LEFT_PLUS", "LEFT_MINUS"})])
    assert not [c for c in drive_commands(sim) if c[0] == "run"]


def test_center_button_cycles_gears_and_remote_light():
    presses = []
    for i in range(4):  # press + release four times: gears 2, 3, 1, 2
        presses += [(100 + i * 200, {"CENTER"}), (200 + i * 200, set())]
    sim = simulate(buttons=[(0, set()), *presses, (1000, {"RIGHT_PLUS"})], until_ms=1200)
    assert [e[2] for e in sim.of("remote light")] == ["GREEN", "YELLOW", "RED", "GREEN", "YELLOW"]
    assert ("run", "B", 600) in drive_commands(sim)


def test_remote_disconnect_stops_motors_and_reconnects():
    sim = simulate(buttons=[(0, {"LEFT_PLUS"}), (500, None), (700, {"RIGHT_PLUS"})], until_ms=15000)
    lost = next(i for i, e in enumerate(sim.events) if e[0] >= 500 and e[1] == "stop")
    assert sim.events[lost][1:] == ("stop", "A")
    assert sim.events[lost + 1][1:] == ("stop", "B")
    assert len(sim.of("remote connected")) == 2
    assert ("run", "B", 300) in drive_commands(sim)


def test_hub_light_shows_search_then_connected():
    sim = simulate(buttons=[(0, set())], remote_failures=1, until_ms=12000)
    assert [e[2] for e in sim.of("hub light")] == ["blink YELLOW", "GREEN"]


def test_low_battery_overrides_hub_light_after_smoothing():
    sim = simulate(buttons=[(0, set())], volts=[(0, 7600), (2000, 6000)], until_ms=20000)
    light = sim.of("hub light")
    assert [e[2] for e in light] == ["blink YELLOW", "GREEN", "blink RED"]
    assert light[-1][0] > 4000  # a short dip under load is smoothed out


def test_debug_output_only_in_debug_build():
    world = {"buttons": [(0, set()), (100, {"LEFT_PLUS"})], "until_ms": 1500}
    assert simulate(**world).output == []
    output = simulate(debug=True, **world).output
    assert "remote connected" in output
    assert "speed 300 0" in output
    assert any(line.startswith("status gear 1 speed 300 0 battery") for line in output)
