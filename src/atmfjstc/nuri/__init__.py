import argparse
import sys
import os
import json
import shutil
import subprocess
import re

from tempfile import TemporaryDirectory
from typing import NoReturn, NamedTuple, Optional, Any, Callable
from pathlib import Path
from base64 import urlsafe_b64encode, urlsafe_b64decode


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


def execute_show_command(context: Context):
    api_path = 'config/' + (context.args.path or '').lstrip('/')
    config = run_json_request(context, api_path)

    json.dump(config, fp=sys.stdout, indent=4, ensure_ascii=False)
    print()


def execute_show_certs_command(context: Context):
    api_path = 'certificates/' + (context.args.path or '').lstrip('/')
    config = run_json_request(context, api_path)

    json.dump(config, fp=sys.stdout, indent=4, ensure_ascii=False)
    print()


def execute_edit_command(context: Context):
    api_path = 'config/' + (context.args.path or '').lstrip('/')

    editor = locate_editor(context.args)

    config = run_json_request(context, api_path)

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

        result = run_json_request(context, api_path, method='PUT', data=new_config, check_error=False)

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


FAKE_URL_PREFIX = "https://localhost:59999/nuri-data/"


def create_data_step(data: dict) -> dict:
    """
    An artificial, impossible-to-match route step that stores data.
    """
    return {
        'match': {
            'arguments': {
                'impossible': urlsafe_b64encode(os.urandom(64)).decode('ascii'),
            },
        },
        'action': {
            'return': 302,
            'location': FAKE_URL_PREFIX + urlsafe_b64encode(json.dumps(data, ensure_ascii=True).encode('ascii')).decode('ascii'),
        },
    }


def locate_data_step(config: dict):
    if 'routes' not in config:
        return None, None

    routes = [config['routes']] if isinstance(config['routes'], list) else config['routes'].values()

    for route in routes:
        for index, step in enumerate(route):
            if ('action' in step) and step['action'].get('location', '').startswith(FAKE_URL_PREFIX):
                return route, index

    return None, None


def retrieve_data_step(config: dict) -> dict:
    route, index = locate_data_step(config)

    if route is None:
        return dict()

    raw_data = route[index]['action']['location'][len(FAKE_URL_PREFIX):].encode('ascii')

    return json.loads(urlsafe_b64decode(raw_data))


def is_data_empty(data: dict) -> bool:
    for value in data.values():
        if isinstance(value, (list, dict)) and (len(value) == 0):
            continue
        return False

    return True


def store_data_step(mut_config: dict, data: dict):
    step = create_data_step(data)

    mut_route, index = locate_data_step(mut_config)

    if mut_route is not None:
        if is_data_empty(data):
            mut_route.pop(index)
        else:
            mut_route[index] = step
        return

    if 'routes' not in mut_config:
        mut_config['routes'] = []

    storage = mut_config['routes']

    if isinstance(storage, dict):
        if len(storage) == 0:
            storage['main'] = []
        for route in storage.values():
            storage = route
            break

    storage.insert(0, step)


def json_search_replace(data: Any, callback: Callable[[Any, tuple], None], head_first: bool = True) -> Any:
    def _json_search_replace_rec(data, path):
        if head_first and isinstance(data, (list, dict)):
            data = callback(data, path)

        if isinstance(data, list):
            data = [_json_search_replace_rec(item, path + (index,)) for index, item in enumerate(data)]
        elif isinstance(data, dict):
            data = {k: _json_search_replace_rec(v, path + (k,)) for k, v in data.items()}
        else:
            data = callback(data, path)

        if not head_first and isinstance(data, (list, dict)):
            data = callback(data, path)

        return data

    return _json_search_replace_rec(data, ())


FAKE_PROXY_PREFIX = "http://unix:/fake-socket/"


def execute_disable_app_command(context: Context):
    app_name = context.args.application

    config = run_json_request(context, 'config/')

    app_config = config['applications'].pop(app_name, None)
    if app_config is None:
        fail(f"Found no active application named '{app_name}'")

    data = retrieve_data_step(config)

    if 'disabled-applications' not in data:
        data['disabled-applications'] = dict()

    data['disabled-applications'][app_name] = app_config

    store_data_step(config, data)

    def _replace(value, _path):
        if isinstance(value, dict) and (value.get('pass') == f"applications/{app_name}"):
            return dict(
                (k, v) if k != 'pass' else ('proxy', f"{FAKE_PROXY_PREFIX}disabled-app-ref/{app_name}")
                for k, v in value.items()
            )

        return value

    config = json_search_replace(config, _replace)

    result = run_json_request(context, 'config/', method='PUT', data=config)
    print_unit_success(result)


def execute_reenable_app_command(context: Context):
    app_name = context.args.application

    config = run_json_request(context, 'config/')

    if app_name in config['applications']:
        fail(f"App '{app_name}' seems to be already enabled")

    data = retrieve_data_step(config)

    app_config = data.get('disabled-applications', dict()).pop(app_name, None)
    if app_config is None:
        fail(f"Found no disabled app named '{app_name}'")

    store_data_step(config, data)

    def _replace(value, _path):
        if isinstance(value, dict) and value.get('proxy', '').startswith(f"{FAKE_PROXY_PREFIX}disabled-app-ref/{app_name}"):
            return dict(
                (k, v) if k != 'proxy' else ('pass', f"applications/{app_name}")
                for k, v in value.items()
            )

        return value

    config = json_search_replace(config, _replace)

    config['applications'][app_name] = app_config

    result = run_json_request(context, 'config/', method='PUT', data=config)
    print_unit_success(result)


def setup_show_command(subparsers):
    parser = subparsers.add_parser('show', help="Show (part of) Unit's configuration")

    parser.add_argument(
        'path', metavar='</path/to/item>', nargs='?',
        help="The subpath to show within the configuration (must exist)"
    )

    parser.set_defaults(exec_command=execute_show_command)


def setup_show_certs_command(subparsers):
    parser = subparsers.add_parser('show-certs', help="Show (part of) Unit's certificates configuration")

    parser.add_argument(
        'path', metavar='</path/to/item>', nargs='?',
        help="The subpath to show within the certificates configuration (must exist)"
    )

    parser.set_defaults(exec_command=execute_show_certs_command)


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


def setup_disable_app_command(subparsers):
    parser = subparsers.add_parser('disable', help="Disable an application")

    parser.add_argument('application', help="The name of the application to disable")

    parser.set_defaults(exec_command=execute_disable_app_command)


def setup_reenable_app_command(subparsers):
    parser = subparsers.add_parser('reenable', help="Re-enable an application")

    parser.add_argument('application', help="The name of the application to re-enable")

    parser.set_defaults(exec_command=execute_reenable_app_command)


def main():
    sanity_checks()

    parser = argparse.ArgumentParser(
        prog="nuri",
        description="NGINX Unit Rough Interface"
    )

    parser.add_argument('-s', '--socket', metavar="<path>", help="The path to Unit's control socket")
    parser.add_argument('-e', '--editor', metavar="<command>", help="Text editor to use (nano, vi etc)")

    subparsers = parser.add_subparsers(title='commands')

    setup_show_command(subparsers)
    setup_show_certs_command(subparsers)
    setup_edit_command(subparsers)
    setup_restart_command(subparsers)
    setup_disable_app_command(subparsers)
    setup_reenable_app_command(subparsers)

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
