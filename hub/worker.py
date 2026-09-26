"""Standalone tank drive: LEGO Powered Up remote (88010) -> motors on ports A and B.

Left +/- drives motor A, right +/- drives motor B, the green center button
cycles the speed gear (shown by the remote light). No PC is needed: store it
with `make download` and start it with the hub button.
"""

from pybricks.hubs import TechnicHub
from pybricks.parameters import Button, Color, Direction, Port
from pybricks.pupdevices import Motor, Remote
from pybricks.tools import StopWatch, wait

# `make debug` uploads a copy with DEBUG = True, which reports status to the PC.
DEBUG = False

# Speed gears as a fraction of the motor's maximum speed, with the remote light color.
GEARS = ((0.3, Color.GREEN), (0.6, Color.YELLOW), (1.0, Color.RED))
REMOTE_TIMEOUT_MS = 10000
LOOP_MS = 20
STATUS_MS = 1000

BATTERY_SAMPLE_MS = 1000
# 6 cells; voltage sags under motor load, hence the smoothing and hysteresis.
LOW_BATTERY_MV = 6500
LOW_BATTERY_HYSTERESIS_MV = 200
BATTERY_SMOOTHING = 0.2

hub = TechnicHub()
# Mirrored mounting: positive speed drives both tracks forward.
motor_a = Motor(Port.A, Direction.COUNTERCLOCKWISE)
motor_b = Motor(Port.B)
MAX_SPEED = min(motor_a.control.limits()[0], motor_b.control.limits()[0])

gear = 0
battery_mv = hub.battery.voltage()
battery_low = False
light_state = None
battery_sample = StopWatch()


def debug(*args):
    if DEBUG:
        print(*args)


def stop_motors():
    motor_a.stop()
    motor_b.stop()


def sample_battery():
    global battery_mv, battery_low
    if battery_sample.time() < BATTERY_SAMPLE_MS:
        return
    battery_sample.reset()
    battery_mv += (hub.battery.voltage() - battery_mv) * BATTERY_SMOOTHING
    threshold = LOW_BATTERY_MV + LOW_BATTERY_HYSTERESIS_MV if battery_low else LOW_BATTERY_MV
    low = battery_mv < threshold
    if low != battery_low:
        battery_low = low
        debug("battery", "low" if low else "ok", int(battery_mv))


def set_light(state):
    global light_state
    if battery_low:
        state = "battery"
    if state == light_state:
        return
    light_state = state
    if state == "battery":
        hub.light.blink(Color.RED, [250, 250])
    elif state == "connected":
        hub.light.on(Color.GREEN)
    else:
        hub.light.blink(Color.YELLOW, [500, 500])


def track_speed(pressed, plus, minus, max_speed):
    if plus in pressed and minus not in pressed:
        return max_speed
    if minus in pressed and plus not in pressed:
        return -max_speed
    return 0


def drive(motor, speed):
    if speed:
        motor.run(speed)
    else:
        motor.stop()


def connect_remote():
    while True:
        set_light("searching")
        debug("searching for remote")
        try:
            remote = Remote(timeout=REMOTE_TIMEOUT_MS)
        except OSError:
            sample_battery()
            continue
        debug("remote connected")
        return remote


def drive_with(remote):
    """Drive until the remote disconnects."""
    global gear
    speeds = (0, 0)
    center_was_pressed = False
    status = StopWatch()
    try:
        remote.light.on(GEARS[gear][1])
        while True:
            pressed = remote.buttons.pressed()

            center = Button.CENTER in pressed
            if center and not center_was_pressed:
                gear = (gear + 1) % len(GEARS)
                remote.light.on(GEARS[gear][1])
                debug("gear", gear + 1)
            center_was_pressed = center

            max_speed = int(GEARS[gear][0] * MAX_SPEED)
            new_speeds = (
                track_speed(pressed, Button.LEFT_PLUS, Button.LEFT_MINUS, max_speed),
                track_speed(pressed, Button.RIGHT_PLUS, Button.RIGHT_MINUS, max_speed),
            )
            if new_speeds != speeds:
                speeds = new_speeds
                drive(motor_a, speeds[0])
                drive(motor_b, speeds[1])
                debug("speed", speeds[0], speeds[1])

            sample_battery()
            set_light("connected")
            if status.time() >= STATUS_MS:
                status.reset()
                debug("status gear", gear + 1, "speed", speeds[0], speeds[1], "battery", int(battery_mv))
            wait(LOOP_MS)
    except OSError:
        # Raised by the remote calls once the remote is switched off or out of range.
        pass


def main():
    stop_motors()
    while True:
        drive_with(connect_remote())
        stop_motors()
        debug("remote disconnected, motors stopped")


main()
