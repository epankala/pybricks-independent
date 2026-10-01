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
    assert "speed 300 0 C 0" in output
    assert any(line.startswith("status gear 1 speed 300 0 0 battery") for line in output)


def light_events(sim):
    return [(e[0], e[3]) for e in sim.of("port light")]


def test_without_port_c_and_d_red_buttons_do_nothing():
    sim = simulate(buttons=[(0, {"RIGHT"}), (500, {"LEFT", "LEFT_PLUS"})])
    assert not [c for c in drive_commands(sim) if c[1] == "C"]
    assert ("run", "A", 300) in drive_commands(sim)
    assert not sim.of("port light")


def test_red_buttons_drive_encoder_motor_on_port_c():
    sim = simulate(
        ports={"C": "motor"},
        buttons=[(0, set()), (100, {"RIGHT"}), (300, set()), (400, {"LEFT"}), (600, {"LEFT", "RIGHT"})],
    )
    assert [c for c in drive_commands(sim) if c[1] == "C" and c[0] == "run"] == [("run", "C", 300), ("run", "C", -300)]
    assert ("stop", "C") == [c for c in drive_commands(sim) if c[1] == "C"][-1]  # both red: cancel out


def test_red_buttons_drive_dc_motor_on_port_c_with_gear_change():
    presses = [(0, set()), (100, {"RIGHT"}), (200, {"RIGHT", "CENTER"}), (300, {"RIGHT"})]
    sim = simulate(ports={"C": "dcmotor"}, buttons=presses, until_ms=500)
    assert [e[1:] for e in sim.of("dc")] == [("dc", "C", 30), ("dc", "C", 60)]  # re-driven at the new gear


def test_light_on_port_d_follows_motors_with_one_minute_idle():
    buttons = [(0, set()), (1000, {"LEFT_PLUS"}), (2000, set()), (30000, {"RIGHT_PLUS"}), (31000, set())]
    sim = simulate(ports={"D": "light"}, buttons=buttons, until_ms=100000)
    assert [state for t, state in light_events(sim)] == ["on", "off"]
    on, off = light_events(sim)
    assert 1000 <= on[0] < 1100
    # The second press restarted the idle minute: off a minute after the last loop that saw it (~31 s).
    assert 90900 <= off[0] < 91100


def test_light_turns_on_for_port_c_motor_too():
    sim = simulate(ports={"C": "motor", "D": "light"}, buttons=[(0, set()), (100, {"LEFT"})])
    assert light_events(sim)[0][1] == "on"


def test_dc_motor_on_port_d_is_not_powered_as_light():
    sim = simulate(ports={"D": "dcmotor"}, buttons=[(0, {"LEFT_PLUS"})])
    assert not sim.of("port light")
    assert not [e for e in sim.events if e[1] in ("dc", "run") and e[2] == "D"]


def test_unplugging_c_and_d_while_driving_keeps_the_remote_connection():
    sim = simulate(
        ports={"C": [(0, "motor"), (500, None)], "D": [(0, "light"), (500, None)]},
        buttons=[(0, {"RIGHT"}), (700, {"RIGHT", "LEFT_PLUS"}), (900, set())],
        until_ms=70000,
    )
    assert len(sim.of("remote connected")) == 1
    assert ("run", "A", 300) in drive_commands(sim)  # still driving after the unplug
    assert [state for t, state in light_events(sim)] == ["on"]  # no off: light is gone


def test_light_turns_off_after_idle_minute_while_searching_for_remote():
    sim = simulate(ports={"D": "light"}, buttons=[(0, {"LEFT_PLUS"}), (500, None)], until_ms=90000)
    on, off = light_events(sim)
    assert on[1] == "on" and off[1] == "off"
    assert 60500 <= off[0] <= 60500 + 10000  # checked between remote searches (10 s each)
