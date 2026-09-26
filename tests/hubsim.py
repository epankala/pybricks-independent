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
    """

    def __init__(self, buttons=(), remote_failures=0, volts=7600, max_speed=1000):
        self.clock = 0
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

        class Light:
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
                self.light = Light("hub")
                self.battery = Battery()

        class Control:
            def limits(self):
                return (sim.max_speed, 2000, 100)

        class Motor:
            def __init__(self, port, positive_direction=Direction.CLOCKWISE):
                self.port = port
                self.control = Control()
                sim.log("motor init", port, positive_direction)

            def run(self, speed):
                sim.log("run", self.port, speed)

            def stop(self):
                sim.log("stop", self.port)

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
                self.light = Light("remote")

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
            "pybricks.parameters": _module(
                "pybricks.parameters", Button=Button, Color=Color, Direction=Direction, Port=Port
            ),
            "pybricks.pupdevices": _module("pybricks.pupdevices", Motor=Motor, Remote=Remote),
            "pybricks.tools": _module("pybricks.tools", StopWatch=StopWatch, wait=sim.advance),
        }


MODULES = ("pybricks", "pybricks.hubs", "pybricks.parameters", "pybricks.pupdevices", "pybricks.tools")


def _module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    return module
