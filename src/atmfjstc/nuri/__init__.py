import argparse
import sys
import os
import json
import shutil
import subprocess
import re

from tempfile import TemporaryDirectory
from typing import NoReturn, NamedTuple, Optional, Any
from pathlib import Path


SOCKET_ENV_KEY = 'NGINX_UNIT_CONTROL_SOCKET'
EDITOR_ENV_KEY = 'EDITOR'


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


def locate_editor(raw_args: argparse.Namespace) -> str:
    editor = None

    if raw_args.editor is not None:
        editor = raw_args.editor
    elif EDITOR_ENV_KEY in os.environ:
        editor = os.environ[EDITOR_ENV_KEY]

    if editor is not None:
        if shutil.which(editor) is None:
            fail(f"Text editor '{editor}' doesn't seem to be available")
        return editor

    for editor in ('nano', 'pico', 'vim', 'vi'):
        if shutil.which(editor) is not None:
            return editor

    fail(
        "Couldn't find any configured text editor, please specify it using either the --editor CLI argument or the "
        f"{EDITOR_ENV_KEY} environment variable."
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
    editor = locate_editor(context.args)

    config = run_json_request(context, context.args.path or '')

    # Trick: we use a js extension so that comments don't break syntax highlighting
    temp_file = context.temp_area / 'temp_edit.js'

    HEADER = (
        "// Edit the configuration below\n"
        "// Lines starting with // will be ignored\n"
        "// To cancel, just leave the file unchanged, or add a line like: // cancel\n"
        "\n"
    )

    with temp_file.open('wt') as f:
        f.write(HEADER)
        json.dump(config, fp=f, indent=4, ensure_ascii=False)

    while True:
        result = subprocess.run([editor, str(temp_file)])
        if result.returncode != 0:
            fail("Editor return code non-zero, something went wrong")

        real_lines = []
        with temp_file.open('rt') as f:
            for line in f:
                if re.match(r'\s*($|//)', line):
                    if re.match(r'\s*//\s*cancel', line, flags=re.I):
                        print("Canceled")
                        sys.exit(-1)
                    continue
                real_lines.append(line)

        error = None
        try:
            new_config = json.loads(''.join(real_lines))
        except json.JSONDecodeError as e:
            error = e

        if error is not None:
            real_lines.insert(error.lineno - 1, f"// JSON error: {error}\n")
            temp_file.write_text(
                HEADER +
                "// There's a JSON error in the config. Look below for a line pointing out the error.\n\n" +
                ''.join(real_lines)
            )
            continue

        result = run_json_request(context, context.args.path or '', method='PUT', data=new_config, check_error=False)

        if isinstance(result, dict) and ('error' in result):
            temp_file.write_text(
                HEADER +
                "// Unit reported an error with the new config:\n" +
                "//\n" +
                ''.join(f"// {line}\n" for line in result['error'].splitlines(keepends=False)) +
                "\n" +
                ''.join(real_lines)
            )
            continue

        print_unit_success(result)
        break


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
    parser.add_argument('-e', '--editor', metavar="<command>", help="Text editor to use (nano, vi etc)")

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
