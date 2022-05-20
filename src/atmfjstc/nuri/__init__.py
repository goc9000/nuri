import argparse
import sys
import os

from typing import NoReturn
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


def main():
    parser = argparse.ArgumentParser(
        prog="nuri",
        description="NGINX Unit Rough Interface"
    )

    parser.add_argument('-s', '--socket', metavar="<path>", help="The path to Unit's control socket")

    raw_args = parser.parse_args()

    socket = locate_control_socket(raw_args)

    # Temp
    print(f"Found socket at: {socket}")
