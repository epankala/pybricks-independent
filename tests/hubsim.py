"""Runs a hub program under CPython against fake ``pybricks`` modules and a simulated clock."""

import sys
import types
from pathlib import Path


class StopSim(Exception):
    pass


class Sim:
    """Scripted world for a hub program.

    ``buttons``: list of ``(t_ms, names)``; from ``t_ms`` on the remote reports those
    buttons pressed (names like "LEFT_PLUS"), or ``None`` for "remote disconnected".
    ``remote_failures``: number of Remote() searches that time out before one succeeds.
    ``volts``: battery voltage in mV, or a list of ``(t_ms, mV)`` steps.
    ``ports``: letter -> device kind ("motor", "dcmotor", "light" or None), or a list of
    ``(t_ms, kind)`` steps for plugging/unplugging; A and B default to "motor".
    """

    def __init__(self, buttons=(), remote_failures=0, volts=7600, max_speed=1000, ports=None):
        self.clock = 0
        self.ports = {"A": "motor", "B": "motor", **(ports or {})}
        self.buttons = sorted(buttons, key=lambda b: b[0])
        self.remote_failures = remote_failures
        self.volts = volts
        self.max_speed = max_speed
        self.events = []  # (t_ms, what, *details)
        self.output = []  # printed lines

    def log(self, *event):
        self.events.append((self.clock, *event))

    def advance(self, ms):
        self.clock += ms
        if self.clock > self.until:
            raise StopSim

    def device_at(self, port):
        spec = self.ports.get(port)
        if not isinstance(spec, list):
            return spec
        return [kind for t, kind in spec if t <= self.clock][-1]

    def pressed_now(self):
        current = set()
        for t, names in self.buttons:
            if t <= self.clock:
                current = names
        return current

    def run(self, path, until_ms, source=None):
        self.until = until_ms
        code = compile(source if source is not None else Path(path).read_text(), str(path), "exec")
        saved = {name: sys.modules.get(name) for name in MODULES}
        sys.modules.update(self._modules())
        try:
            exec(code, {"__name__": "__main__", "print": lambda *a: self.output.append(" ".join(map(str, a)))})
        except StopSim:
            pass
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module
        return self

    def of(self, what):
        return [e for e in self.events if e[1] == what]

    def _modules(self):
        sim = self

        class Enum:
            def __init__(self, names):
                for name in names:
                    setattr(self, name, name)

        Button = Enum("LEFT_PLUS LEFT_MINUS LEFT RIGHT_PLUS RIGHT_MINUS RIGHT CENTER".split())
        Color = Enum("RED GREEN YELLOW BLUE".split())
        Direction = Enum(["CLOCKWISE", "COUNTERCLOCKWISE"])
        Port = Enum("A B C D".split())

        class StatusLight:
            def __init__(self, owner):
                self.owner = owner

            def on(self, color):
                sim.log(f"{self.owner} light", color)

            def blink(self, color, durations):
                sim.log(f"{self.owner} light", f"blink {color}")

        class Battery:
            def voltage(self):
                if isinstance(sim.volts, int):
                    return sim.volts
                return [mv for t, mv in sim.volts if t <= sim.clock][-1]

            def current(self):
                return 100

        class TechnicHub:
            def __init__(self):
                self.light = StatusLight("hub")
                self.battery = Battery()

        class Control:
            def limits(self):
                return (sim.max_speed, 2000, 100)

        class PortDevice:
            kinds = ()

            def __init__(self, port):
                self.port = port
                self.kind = sim.device_at(port)
                if self.kind not in self.kinds:
                    raise OSError(19, f"no {type(self).__name__} on port {port}")

            def plugged(self):
                if sim.device_at(self.port) != self.kind:
                    raise OSError(19, "device unplugged")

        class PUPDevice(PortDevice):
            kinds = ("motor", "dcmotor", "light")
            IDS = {"motor": 48, "dcmotor": 2, "light": 8}

            def info(self):
                return {"id": self.IDS[self.kind]}

        class Motor(PortDevice):
            kinds = ("motor",)

            def __init__(self, port, positive_direction=Direction.CLOCKWISE):
                super().__init__(port)
                self.control = Control()
                sim.log("motor init", port, positive_direction)

            def run(self, speed):
                self.plugged()
                sim.log("run", self.port, speed)

            def stop(self):
                self.plugged()
                sim.log("stop", self.port)

        class DCMotor(PortDevice):
            kinds = ("dcmotor", "motor")

            def dc(self, duty):
                self.plugged()
                sim.log("dc", self.port, duty)

            def stop(self):
                self.plugged()
                sim.log("stop", self.port)

        class Light(PortDevice):
            # Assumed as permissive as a DC output: it would also power a DC motor.
            kinds = ("light", "dcmotor")

            def on(self, brightness=100):
                self.plugged()
                sim.log("port light", self.port, "on", brightness)

            def off(self):
                self.plugged()
                sim.log("port light", self.port, "off")

        class Buttons:
            def pressed(self):
                current = sim.pressed_now()
                if current is None:
                    raise OSError(19, "remote disconnected")
                return {getattr(Button, name) for name in current}

        class Remote:
            def __init__(self, name=None, timeout=10000):
                if sim.remote_failures:
                    sim.remote_failures -= 1
                    sim.advance(timeout)
                    raise OSError(110, "timed out")
                if sim.pressed_now() is None:
                    sim.advance(timeout)
                    raise OSError(110, "timed out")
                sim.log("remote connected")
                self.buttons = Buttons()
                self.light = StatusLight("remote")

        class StopWatch:
            def __init__(self):
                self.t0 = sim.clock

            def reset(self):
                self.t0 = sim.clock

            def time(self):
                return sim.clock - self.t0

        return {
            "pybricks": types.ModuleType("pybricks"),
            "pybricks.hubs": _module("pybricks.hubs", TechnicHub=TechnicHub),
            "pybricks.iodevices": _module("pybricks.iodevices", PUPDevice=PUPDevice),
            "pybricks.parameters": _module(
                "pybricks.parameters", Button=Button, Color=Color, Direction=Direction, Port=Port
            ),
            "pybricks.pupdevices": _module(
                "pybricks.pupdevices", DCMotor=DCMotor, Light=Light, Motor=Motor, Remote=Remote
            ),
            "pybricks.tools": _module("pybricks.tools", StopWatch=StopWatch, wait=sim.advance),
        }


MODULES = (
    "pybricks",
    "pybricks.hubs",
    "pybricks.iodevices",
    "pybricks.parameters",
    "pybricks.pupdevices",
    "pybricks.tools",
)


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module
