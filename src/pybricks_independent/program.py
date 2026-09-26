"""Hub program handling that needs no hub: debug builds and local compilation."""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pybricksdev.compile import compile_multi_file

DEBUG_OFF = "DEBUG = False"
DEBUG_ON = "DEBUG = True"
# Bytecode format of Pybricks v3.2+ firmware; the hub may also accept newer ones.
MPY_ABI = 6


def debug_source(text: str) -> str | None:
    """The program with its ``DEBUG = False`` line switched on, or None if it has none."""
    if text.count(DEBUG_OFF) != 1:
        return None
    return text.replace(DEBUG_OFF, DEBUG_ON)


@contextmanager
def debug_build(path: Path) -> Iterator[Path | None]:
    """A debug copy of the program next to its local modules; None if it has no DEBUG switch."""
    text = debug_source(path.read_text())
    if text is None:
        yield None
        return
    # Same directory, so local imports still resolve when pybricksdev compiles it.
    # The name must be a valid module name for pybricksdev's compiler.
    with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=f"_{path.stem}_debug_", suffix=".py") as f:
        f.write(text)
        f.flush()
        yield Path(f.name)


async def compile_program(path: Path) -> bytes:
    """The upload image pybricksdev sends to the hub: per module a uint32 LE size,
    the zero-terminated module name and its MicroPython bytecode."""
    return await compile_multi_file(str(path), MPY_ABI)


def image_modules(image: bytes) -> dict[str, bytes]:
    """Split an upload image into module name -> bytecode."""
    modules = {}
    offset = 0
    while offset < len(image):
        size = int.from_bytes(image[offset : offset + 4], "little")
        name_end = image.index(b"\0", offset + 4)
        name = image[offset + 4 : name_end].decode()
        modules[name] = image[name_end + 1 : name_end + 1 + size]
        offset = name_end + 1 + size
    return modules
