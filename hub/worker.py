"""Standalone tank drive: LEGO Powered Up remote (88010) -> motors on ports A and B.

Left +/- drives motor A, right +/- drives motor B, the green center button
cycles the speed gear (shown by the remote light). Optional: a motor on port C
is driven by the red buttons, and a light on port D is on while motors run and
for a minute after. No PC is needed: store it with `make download` and start
it with the hub button.
"""

from pybricks.hubs import TechnicHub
from pybricks.iodevices import PUPDevice
from pybricks.parameters import Button, Color, Direction, Port
from pybricks.pupdevices import DCMotor, Light, Motor, Remote
from pybricks.tools import StopWatch, wait

# `make debug` uploads a copy with DEBUG = True, which reports status to the PC.
DEBUG = False

# Speed gears as a fraction of the motor's maximum speed, with the remote light color.
GEARS = ((0.3, Color.GREEN), (0.6, Color.YELLOW), (1.0, Color.RED))
REMOTE_TIMEOUT_MS = 10000
LOOP_MS = 20
STATUS_MS = 1000
LIGHT_IDLE_MS = 60000

# Device type ids (PUPDevice.info()["id"]) of the passive devices used here.
DC_MOTOR_IDS = (1, 2)  # Powered Up Medium Motor, Train Motor
LIGHT_ID = 8

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

# Optional devices, (re)detected whenever the remote connects; None if absent.
motor_c = None
light_d = None
light_d_on = False
idle = StopWatch()

gear = 0
battery_mv = hub.battery.voltage()
battery_low = False
light_state = None
battery_sample = StopWatch()


def debug(*args):
    if DEBUG:
        print(*args)


def device_id(port):
    try:
        return PUPDevice(port).info()["id"]
    except OSError:
        return None


def attach_optional_devices():
    global motor_c, light_d
    try:
        motor_c = Motor(Port.C)
    except OSError:
        # Plain motors without an encoder (e.g. train motor) need DCMotor.
        motor_c = DCMotor(Port.C) if device_id(Port.C) in DC_MOTOR_IDS else None
    # Checked by id: a DC motor on port D must not be powered as if it were a light.
    light_d = Light(Port.D) if device_id(Port.D) == LIGHT_ID else None
    debug("port C:", "motor" if motor_c else "none", "port D:", "light" if light_d else "none")


def drive_c(direction):
    """Run motor C at the current gear in the given direction (-1, 0, 1)."""
    global motor_c
    if motor_c is None:
        return
    try:
        if not direction:
            motor_c.stop()
        elif isinstance(motor_c, Motor):
            motor_c.run(direction * int(GEARS[gear][0] * motor_c.control.limits()[0]))
        else:
            motor_c.dc(direction * int(GEARS[gear][0] * 100))
    except OSError:
        motor_c = None
        debug("motor C unplugged")


def update_light_d(moving):
    """Light D is on while any motor runs and for LIGHT_IDLE_MS after the last one stops."""
    global light_d, light_d_on
    if moving:
        idle.reset()
    want_on = moving or (light_d_on and idle.time() < LIGHT_IDLE_MS)
    if light_d is None or want_on == light_d_on:
        return
    try:
        if want_on:
            light_d.on(100)
        else:
            light_d.off()
    except OSError:
        light_d = None
        debug("light D unplugged")
        return
    light_d_on = want_on
    debug("light D", "on" if want_on else "off")


def stop_motors():
    motor_a.stop()
    motor_b.stop()
    drive_c(0)


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


def direction(pressed, plus, minus):
    if plus in pressed and minus not in pressed:
        return 1
    if minus in pressed and plus not in pressed:
        return -1
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
            update_light_d(False)
            continue
        debug("remote connected")
        return remote


def drive_with(remote):
    """Drive until the remote disconnects."""
    global gear
    speeds = (0, 0, 0)
    center_was_pressed = False
    status = StopWatch()
    attach_optional_devices()
    try:
        remote.light.on(GEARS[gear][1])
        while True:
            pressed = remote.buttons.pressed()

            center = Button.CENTER in pressed
            if center and not center_was_pressed:
                gear = (gear + 1) % len(GEARS)
                remote.light.on(GEARS[gear][1])
                debug("gear", gear + 1)
                speeds = None  # re-drive all motors at the new gear, also motor C whose direction is unchanged
            center_was_pressed = center

            max_speed = int(GEARS[gear][0] * MAX_SPEED)
            new_speeds = (
                direction(pressed, Button.LEFT_PLUS, Button.LEFT_MINUS) * max_speed,
                direction(pressed, Button.RIGHT_PLUS, Button.RIGHT_MINUS) * max_speed,
                # Red buttons: right forward, left backward; scaled per motor type in drive_c.
                direction(pressed, Button.RIGHT, Button.LEFT) if motor_c else 0,
            )
            if new_speeds != speeds:
                speeds = new_speeds
                drive(motor_a, speeds[0])
                drive(motor_b, speeds[1])
                drive_c(speeds[2])
                debug("speed", speeds[0], speeds[1], "C", speeds[2])
            update_light_d(any(speeds))

            sample_battery()
            set_light("connected")
            if status.time() >= STATUS_MS:
                status.reset()
                debug("status gear", gear + 1, "speed", *speeds, "battery", int(battery_mv))
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
