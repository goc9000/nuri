import argparse
import sys
import os
import json
import shutil
import subprocess

from tempfile import TemporaryDirectory
from typing import NoReturn, NamedTuple, Optional, Any
from pathlib import Path


SOCKET_ENV_KEY = 'NGINX_UNIT_CONTROL_SOCKET'


def fail(message: str) -> NoReturn:
    print(message, file=sys.stderr)
    sys.exit(-1)


def sanity_checks():
    if shutil.which('curl') is None:
        fail("The 'curl' command is not available")


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


def run_raw_request(context: Context, path: str, method: str = 'GET', data: Optional[str] = None) -> str:
    args = [
        'curl',
        '--unix-socket', str(context.socket),
        '-X', method,
        f"http://localhost/{path.lstrip('/')}",
    ]
    if data is not None:
        args.append('--data')
        args.append('@-')

    result = subprocess.run(
        args,
        input=data,
        capture_output=True,
        text=True
    )

    if result.returncode == 7:
        fail("CURL couldn't connect to the socket, probably a permissions issue, rerun with sudo")
    if result.returncode != 0:
        fail(f"CURL request failed, response:\n{result.stderr}")

    return result.stdout


def run_json_request(
    context: Context, path: str, method: str = 'GET', data: Optional[Any] = None, check_error: bool = True
) -> Any:
    data_json = json.dumps(data) if data is not None else None

    json_text = run_raw_request(context, path, method, data_json)

    result = json.loads(json_text)

    if check_error and isinstance(result, dict) and ('error' in result):
        fail(f"Error: {result['error']}")

    return result


def print_unit_success(result: Any):
    if isinstance(result, dict) and ('success' in result):
        print(result['success'])


def execute_edit_command(context: Context):
    print("(stub for command: edit)")


def execute_restart_command(context: Context):
    # You'd think a POST would be more appropriate for this, but the documentation says GET so...
    result = run_json_request(context, f'control/applications/{context.args.application}/restart')

    print_unit_success(result)


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
    sanity_checks()

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
