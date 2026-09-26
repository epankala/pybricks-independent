"""Compile, upload and debug standalone Pybricks hub programs.

The hub program runs on its own once uploaded; the PC is only needed to put
it there, or to watch its output in debug mode.
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from bleak.exc import BleakError, BleakGATTProtocolError
from pybricksdev.ble import find_device
from pybricksdev.ble.pybricks import CommandError, StatusFlag
from pybricksdev.connections import ConnectionState
from pybricksdev.connections.pybricks import HubDisconnectError, PybricksHubBLE

from . import program

logger = logging.getLogger("pybricks_independent")

CONNECT_RETRY_DELAY = 1.0
# A program left running on the hub makes uploads and starts fail with BUSY.
STOP_PROGRAM_RETRIES = 3
STOP_PROGRAM_SETTLE = 0.5
# Failures worth a fresh attempt; typically a flaky BLE link during upload.
RETRY_ERRORS = (BleakError, HubDisconnectError, TimeoutError, asyncio.TimeoutError)


class HubNotFound(Exception):
    pass


def error_text(e: BaseException) -> str:
    return str(e.args[-1]) if e.args else type(e).__name__


async def stop_program_and_settle(hub: PybricksHubBLE) -> None:
    await hub.stop_user_program()
    await asyncio.sleep(STOP_PROGRAM_SETTLE)


async def unless_busy(hub: PybricksHubBLE, operation: Callable[[], Awaitable[None]]) -> None:
    """Run a hub operation, stopping a running program first if it is in the way."""
    if hub.status_observable.value & StatusFlag.USER_PROGRAM_RUNNING:
        logger.info("hub is running a program, stopping it")
        await stop_program_and_settle(hub)
    for attempt in range(STOP_PROGRAM_RETRIES + 1):
        try:
            await operation()
            return
        except BleakGATTProtocolError as e:
            # Status reports arrive asynchronously, so a running program may only show up as BUSY.
            if e.args[0] != CommandError.BUSY or attempt == STOP_PROGRAM_RETRIES:
                raise
            logger.info("hub is busy running a program, stopping it")
            await stop_program_and_settle(hub)


async def disconnect_quietly(hub: PybricksHubBLE) -> None:
    try:
        await hub.disconnect()
    except Exception as e:  # the link is usually already broken here
        logger.debug("disconnect failed: %s", e)


async def connect(args: argparse.Namespace, prepare: Callable[[PybricksHubBLE], Awaitable[None]]) -> PybricksHubBLE:
    """Connect and run ``prepare``, retrying both on BLE failures. The caller must disconnect."""
    for attempt in range(1, args.attempts + 1):
        logger.info("scanning for hub %s...", args.hub_name or "(any Pybricks hub)")
        try:
            device = await find_device(args.hub_name, timeout=args.scan_timeout)
        except asyncio.TimeoutError:
            raise HubNotFound(f"no hub found within {args.scan_timeout:.0f} s") from None
        hub = PybricksHubBLE(device)
        try:
            await hub.connect()
            logger.info("connected to %s, Pybricks firmware %s", device.name, hub.fw_version)
            await prepare(hub)
            return hub
        except RETRY_ERRORS as e:
            await disconnect_quietly(hub)
            if attempt == args.attempts:
                raise
            logger.warning("attempt %d/%d failed: %s; retrying", attempt, args.attempts, error_text(e))
            await asyncio.sleep(CONNECT_RETRY_DELAY)
    raise AssertionError("unreachable")


async def wait_program_stopped(hub: PybricksHubBLE) -> None:
    seen_running = False
    stopped = asyncio.Event()

    def on_status(flags: StatusFlag) -> None:
        nonlocal seen_running
        if flags & StatusFlag.USER_PROGRAM_RUNNING:
            seen_running = True
        elif seen_running:
            stopped.set()

    with hub.status_observable.subscribe(on_status):
        await hub.race_disconnect(stopped.wait())


async def print_hub_output(hub: PybricksHubBLE) -> None:
    while True:
        line = await hub.read_line()
        print(f"{datetime.now():%H:%M:%S.%f}"[:-3], line, flush=True)


async def cmd_compile(args: argparse.Namespace) -> int:
    image = await program.compile_program(args.program)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    modules = ", ".join(program.image_modules(image))
    logger.info("compiled %s -> %s (%d bytes; modules: %s)", args.program, args.output, len(image), modules)
    return 0


async def cmd_download(args: argparse.Namespace) -> int:
    hub = await connect(args, lambda hub: unless_busy(hub, lambda: hub.download(str(args.program))))
    await disconnect_quietly(hub)
    logger.info("stored %s on the hub; start it with the hub button", args.program)
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    async def prepare(hub: PybricksHubBLE) -> None:
        await unless_busy(hub, lambda: hub.download(str(args.program)))
        await unless_busy(hub, hub.start_user_program)

    hub = await connect(args, prepare)
    await disconnect_quietly(hub)
    logger.info("started %s; it keeps running without the PC", args.program)
    return 0


async def cmd_debug(args: argparse.Namespace) -> int:
    with program.debug_build(args.program) as debug_path:
        if debug_path is None:
            logger.warning("%s has no %r line; running it unmodified", args.program, program.DEBUG_OFF)
        path = str(debug_path or args.program)

        async def prepare(hub: PybricksHubBLE) -> None:
            await unless_busy(hub, lambda: hub.run(path, wait=False, print_output=False))

        hub = await connect(args, prepare)

    logger.info("streaming hub output; Ctrl-C stops the program")
    tasks = [asyncio.create_task(print_hub_output(hub)), asyncio.create_task(wait_program_stopped(hub))]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        logger.info("hub program stopped")
        return 0
    except HubDisconnectError:
        logger.error("hub disconnected")
        return 1
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if hub.connection_state_observable.value == ConnectionState.CONNECTED:
            try:
                await hub.stop_user_program()
            except Exception as e:  # best effort during teardown
                logger.debug("stopping hub program failed: %s", e)
        await disconnect_quietly(hub)


async def cmd_stop(args: argparse.Namespace) -> int:
    hub = await connect(args, lambda hub: hub.stop_user_program())
    await disconnect_quietly(hub)
    logger.info("hub program stopped")
    return 0


COMMANDS = {
    "compile": (cmd_compile, "compile locally into the hub upload image (no hub needed)"),
    "download": (cmd_download, "store the program on the hub; start it with the hub button"),
    "run": (cmd_run, "store and start the program, then disconnect"),
    "debug": (cmd_debug, "run a DEBUG = True copy and stream its output until it stops"),
    "stop": (cmd_stop, "stop the program running on the hub"),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="pybricks-independent", description=__doc__.splitlines()[0])
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    hub_options = argparse.ArgumentParser(add_help=False)
    hub_options.add_argument("-n", "--hub-name", help="hub Bluetooth name or address (default: first found)")
    hub_options.add_argument(
        "--scan-timeout", type=float, default=10.0, help="scan timeout in s (default: %(default)s)"
    )
    hub_options.add_argument("--attempts", type=int, default=3, help="connect/upload attempts (default: %(default)s)")

    commands = parser.add_subparsers(dest="command", required=True)
    for name, (_, help_text) in COMMANDS.items():
        parents = [] if name == "compile" else [hub_options]
        sub = commands.add_parser(name, help=help_text, description=help_text, parents=parents)
        if name != "stop":
            sub.add_argument("program", type=Path, help="hub program (.py)")
        if name == "compile":
            sub.add_argument("-o", "--output", type=Path, help="output file (default: build/<program>.bin)")

    args = parser.parse_args(argv)
    if getattr(args, "attempts", 1) < 1:
        parser.error("--attempts must be at least 1")
    if args.command == "compile" and args.output is None:
        args.output = Path("build") / args.program.with_suffix(".bin").name
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S", stream=sys.stderr
    )
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    handler = COMMANDS[args.command][0]
    try:
        return asyncio.run(handler(args))
    except KeyboardInterrupt:
        return 130
    except (HubNotFound, OSError, BleakError, RuntimeError) as e:
        logger.error("%s", error_text(e))
        return 1
