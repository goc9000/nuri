import argparse
import sys
import os

from tempfile import TemporaryDirectory
from typing import NoReturn, NamedTuple
from pathlib import Path


SOCKET_ENV_KEY = 'NGINX_UNIT_CONTROL_SOCKET'


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(-1)


def locate_control_socket(raw_args: argparse.Namespace) -> Path:
    socket = None

    if raw_args.socket is not None:
        socket = Path(raw_args.socket)
    elif SOCKET_ENV_KEY in os.environ:
        socket = Path(os.environ[SOCKET_ENV_KEY])

    if socket is not None:
        if not socket.is_socket():
            fail(f"Couldn't find Unit control socket at {socket}")
        return socket

    for base in ('/var/run', '/run', '/usr/local/var/run'):
        base_path = Path(base)
        if not base_path.exists():
            continue

        for subpath in ('unit/control.sock', 'control.unit.sock', 'nginx-unit.control.sock', 'nginx-unit/control.sock'):
            socket = base_path / subpath
            if socket.is_socket():
                return socket

    fail(
        "Couldn't find Unit control socket in the usual locations, please specify it using either the --socket CLI "
        f"argument or the {SOCKET_ENV_KEY} environment variable."
    )


class Context(NamedTuple):
    args: argparse.Namespace
    socket: Path
    temp_area: Path


def execute_edit_command(context: Context):
    print("(stub for command: edit)")


def execute_restart_command(context: Context):
    print("(stub for command: restart)")


def setup_edit_command(subparsers):
    parser = subparsers.add_parser('edit', help="Interactively edit Unit's configuration")

    parser.add_argument(
        'path', metavar='</path/to/item>', nargs='?',
        help="The subpath to edit within the configuration (must exist)"
    )

    parser.set_defaults(exec_command=execute_edit_command)


def setup_restart_command(subparsers):
    parser = subparsers.add_parser('restart', help="Restart an application")

    parser.add_argument('application', help="The name of the application to restart")

    parser.set_defaults(exec_command=execute_restart_command)


def main():
    parser = argparse.ArgumentParser(
        prog="nuri",
        description="NGINX Unit Rough Interface"
    )

    parser.add_argument('-s', '--socket', metavar="<path>", help="The path to Unit's control socket")

    subparsers = parser.add_subparsers(title='commands')

    setup_edit_command(subparsers)
    setup_restart_command(subparsers)

    raw_args = parser.parse_args()

    if 'exec_command' not in raw_args:
        parser.print_usage()
        sys.exit(-1)

    with TemporaryDirectory(prefix='/dev/shm/nuri-') as temp_dir:
        socket = locate_control_socket(raw_args)

        raw_args.exec_command(Context(
            args=raw_args,
            socket=socket,
            temp_area=Path(temp_dir),
        ))
