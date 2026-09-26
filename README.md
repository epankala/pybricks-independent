# pybricks-independent

Standalone [Pybricks](https://pybricks.com) hub programs: the program runs on the hub by
itself, with no PC in the loop. The PC is only used to compile and upload it, or to watch
its output in debug mode.

The sample program (`hub/worker.py`) drives a Technic Hub with the LEGO Powered Up remote
(88010).

## Setup and use

```sh
make install     # .venv + editable install of the tool with dev tools
make download    # store hub/worker.py on the hub; start it with the hub button
make run         # store and start it now, then disconnect (keeps running)
make debug       # run a DEBUG build and stream its output until it stops (Ctrl-C stops it)
make stop        # stop the program running on the hub
make compile     # compile locally into build/worker.bin (no hub needed)
make check       # ruff + pytest (incl. simulated hub program) + compile
```

Options: `PROGRAM=hub/other.py` picks another hub program, `HUB="Pybricks Hub"` a hub by
name, `ARGS="..."` passes tool options (`--attempts`, `--scan-timeout`, `-v`). Without make:
`pip install -e .` and `pybricks-independent --help`.

Pybricks keeps the uploaded program on the hub, also across power-offs, so after
`make download` the hub works without the PC: press its button to start the program.

Uploads are retried (`--attempts`, default 3) since BLE links occasionally drop mid-upload,
and a program already running on the hub is stopped first.

## Sample program: remote-controlled tank drive

No pairing needed: switch on the remote and the hub connects to the first one it finds.

| Remote             | Action                                   |
|--------------------|------------------------------------------|
| Left + / −         | Motor A forward / backward (while held)  |
| Right + / −        | Motor B forward / backward (while held)  |
| Green center       | Next speed gear: 30 % / 60 % / 100 %     |

The motors use closed-loop speed control (`Motor.run`), so speed holds under load and at
low battery. Motor A is mounted mirrored (`Direction.COUNTERCLOCKWISE`), so + drives both
tracks forward. The remote light shows the gear (green / yellow / red).

| Hub light         | Meaning                                         |
|-------------------|-------------------------------------------------|
| Yellow, blinking  | Searching for the remote                        |
| Green             | Remote connected                                |
| Red, blinking     | Low battery (overrides the others)              |

If the remote switches off or goes out of range, the motors stop and the hub searches
for it again.

## Debug mode

`make debug` uploads a copy of the program with its `DEBUG = False` line switched to
`DEBUG = True` and streams everything it prints, timestamped, to stdout (the tool's own
log goes to stderr, so `make debug > log.txt` captures only hub output). The sample
program then reports connections, gear changes, motor speeds and a status line every
second. Your own programs opt in by having a `DEBUG = False` line; without it, debug runs
them unmodified. The debug build stays stored on the hub afterwards; `make download`
puts the normal one back.

## Writing hub programs

Hub programs are MicroPython files under `hub/`. Local imports work: pybricksdev compiles
the imported modules into the same upload image. `tests/hubsim.py` runs a hub program under
CPython against fake `pybricks` modules with a simulated clock; see `tests/test_worker.py`.
