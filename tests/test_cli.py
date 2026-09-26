import argparse
import asyncio
from pathlib import Path

import pytest
from bleak.exc import BleakGATTProtocolError, BleakGATTProtocolErrorCode
from pybricksdev.ble.pybricks import CommandError, StatusFlag
from pybricksdev.connections import ConnectionState
from reactivex.subject import BehaviorSubject

from pybricks_independent import cli, program

UNLIKELY = BleakGATTProtocolErrorCode.UNLIKELY_ERROR
WORKER = Path(__file__).parent.parent / "hub" / "worker.py"


@pytest.fixture(autouse=True)
def no_delays(monkeypatch):
    monkeypatch.setattr(cli, "STOP_PROGRAM_SETTLE", 0)
    monkeypatch.setattr(cli, "CONNECT_RETRY_DELAY", 0)


class FakeHub:
    """Records calls; ``failures`` maps a call name to errors raised by its successive calls."""

    fw_version = "3.6.1"

    def __init__(self, failures=None, status=None):
        self.status_observable = BehaviorSubject(status or StatusFlag(0))
        self.connection_state_observable = BehaviorSubject(ConnectionState.DISCONNECTED)
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.calls = []

    async def _call(self, name, *args):
        self.calls.append(name)
        errors = self.failures.get(name)
        if errors:
            raise errors.pop(0)

    async def connect(self):
        await self._call("connect")
        self.connection_state_observable.on_next(ConnectionState.CONNECTED)

    async def disconnect(self):
        self.calls.append("disconnect")
        self.connection_state_observable.on_next(ConnectionState.DISCONNECTED)

    async def download(self, path):
        await self._call("download")
        self.downloaded = Path(path).read_text()

    async def start_user_program(self):
        await self._call("start")

    async def run(self, path, wait, print_output):
        await self._call("run")
        self.downloaded = Path(path).read_text()
        self.status_observable.on_next(StatusFlag.USER_PROGRAM_RUNNING)

    async def stop_user_program(self):
        self.calls.append("stop")
        self.status_observable.on_next(StatusFlag(0))

    async def read_line(self):
        await asyncio.sleep(3600)

    async def race_disconnect(self, awaitable):
        return await awaitable


def busy():
    return BleakGATTProtocolError(CommandError.BUSY)


def run_command(monkeypatch, argv, hubs):
    """Run a CLI command against the given FakeHubs, one per connection attempt."""
    hubs = list(hubs)

    async def fake_find_device(name, timeout):
        return argparse.Namespace(name="Pybricks Hub")

    monkeypatch.setattr(cli, "find_device", fake_find_device)
    monkeypatch.setattr(cli, "PybricksHubBLE", lambda device: hubs.pop(0))
    args = cli.parse_args(argv)
    return asyncio.run(cli.COMMANDS[args.command][0](args))


def test_parse_args_defaults_compile_output():
    args = cli.parse_args(["compile", "hub/worker.py"])
    assert args.output == Path("build/worker.bin")


def test_parse_args_rejects_zero_attempts():
    with pytest.raises(SystemExit):
        cli.parse_args(["download", "--attempts", "0", "hub/worker.py"])


def test_download_stores_without_starting(monkeypatch):
    hub = FakeHub()
    assert run_command(monkeypatch, ["download", str(WORKER)], [hub]) == 0
    assert hub.calls == ["connect", "download", "disconnect"]


def test_run_stores_and_starts(monkeypatch):
    hub = FakeHub()
    run_command(monkeypatch, ["run", str(WORKER)], [hub])
    assert hub.calls == ["connect", "download", "start", "disconnect"]


def test_busy_hub_program_is_stopped_first(monkeypatch):
    hub = FakeHub(failures={"download": [busy()]})
    run_command(monkeypatch, ["download", str(WORKER)], [hub])
    assert hub.calls == ["connect", "download", "stop", "download", "disconnect"]


def test_program_known_to_be_running_is_stopped_first(monkeypatch):
    hub = FakeHub(status=StatusFlag.USER_PROGRAM_RUNNING)
    run_command(monkeypatch, ["download", str(WORKER)], [hub])
    assert hub.calls == ["connect", "stop", "download", "disconnect"]


def test_upload_failure_reconnects_and_retries(monkeypatch):
    first, second = FakeHub(failures={"download": [BleakGATTProtocolError(UNLIKELY)]}), FakeHub()
    assert run_command(monkeypatch, ["download", str(WORKER)], [first, second]) == 0
    assert first.calls == ["connect", "download", "disconnect"]
    assert second.calls == ["connect", "download", "disconnect"]


def test_gives_up_after_attempts(monkeypatch):
    hubs = [FakeHub(failures={"connect": [TimeoutError()]}) for _ in range(2)]
    with pytest.raises(TimeoutError):
        run_command(monkeypatch, ["download", "--attempts", "2", str(WORKER)], hubs)


def test_debug_uploads_debug_build_and_stops_program_on_exit(monkeypatch):
    hub = FakeHub()

    async def stop_soon():
        await asyncio.sleep(0.01)
        hub.status_observable.on_next(StatusFlag(0))  # program ends, e.g. hub button

    async def run_debug():
        args = cli.parse_args(["debug", str(WORKER)])
        stopper = asyncio.create_task(stop_soon())
        code = await cli.cmd_debug(args)
        await stopper
        return code

    async def fake_find_device(name, timeout):
        return argparse.Namespace(name="Pybricks Hub")

    monkeypatch.setattr(cli, "find_device", fake_find_device)
    monkeypatch.setattr(cli, "PybricksHubBLE", lambda device: hub)
    assert asyncio.run(run_debug()) == 0
    assert "DEBUG = True" in hub.downloaded
    assert hub.calls == ["connect", "run", "stop", "disconnect"]
    assert not list(WORKER.parent.glob("_*_debug_*.py"))


def test_compile_writes_mpy(tmp_path):
    out = tmp_path / "out" / "worker.bin"
    args = cli.parse_args(["compile", str(WORKER), "-o", str(out)])
    assert asyncio.run(cli.cmd_compile(args)) == 0
    assert list(program.image_modules(out.read_bytes())) == ["__main__"]
