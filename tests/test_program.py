import asyncio
from pathlib import Path

from pybricks_independent import program

WORKER = Path(__file__).parent.parent / "hub" / "worker.py"


def test_debug_source_switches_debug_on():
    assert program.debug_source("x = 1\nDEBUG = False\n") == "x = 1\nDEBUG = True\n"


def test_debug_source_requires_single_switch():
    assert program.debug_source("x = 1\n") is None
    assert program.debug_source("DEBUG = False\nDEBUG = False\n") is None


def test_debug_build_is_temporary_copy_next_to_program(tmp_path):
    source = tmp_path / "prog.py"
    source.write_text("DEBUG = False\nprint(DEBUG)\n")
    with program.debug_build(source) as path:
        assert path.parent == tmp_path
        assert path.read_text() == "DEBUG = True\nprint(DEBUG)\n"
    assert not path.exists()
    assert source.read_text() == "DEBUG = False\nprint(DEBUG)\n"


def test_debug_build_without_switch_yields_none(tmp_path):
    source = tmp_path / "prog.py"
    source.write_text("print(1)\n")
    with program.debug_build(source) as path:
        assert path is None


def bytecode_versions(image):
    return {name: code[:2] for name, code in program.image_modules(image).items()}


def test_sample_worker_compiles_including_debug_build():
    image = asyncio.run(program.compile_program(WORKER))
    assert bytecode_versions(image) == {"__main__": b"M\x06"}  # MicroPython bytecode v6
    with program.debug_build(WORKER) as debug_path:
        assert bytecode_versions(asyncio.run(program.compile_program(debug_path))) == {"__main__": b"M\x06"}


def test_multi_file_program_includes_local_modules(tmp_path):
    (tmp_path / "helpers.py").write_text("def double(x):\n    return 2 * x\n")
    main = tmp_path / "main.py"
    main.write_text("from helpers import double\nprint(double(2))\n")
    image = asyncio.run(program.compile_program(main))
    assert set(program.image_modules(image)) == {"__main__", "helpers"}
