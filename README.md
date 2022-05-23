Nuri
====


## About

Nuri (NGINX Unit Rough Interface) is a quick & dirty utility for helping with the control and configuration of the
[NGINX Unit](https://unit.nginx.org) application server.

NGINX Unit features an... innovative? different? way for the administrator to interact with the service and its
configuration. Instead of editing config files in `/etc` or calling a CLI utility to control aspects of the service,
the admin makes configuration and runtime changes by submitting HTTP requests to a control socket featuring a
JSON-based API.

That's all fine and dandy, but for now the only official way to interact with the socket is to submit requests to it
in the command line via `curl`. Even the official docs, such as they are, are rife with examples such as:

    curl -X PUT -d '{ "pass": "applications/blogs" }' --unix-socket \
        /path/to/control.unit.sock http://localhost/config/listeners/127.0.0.1:8300

This isn't great.

The Unit devs claim a CLI frontend is in the making, but until that is done, I've jury-rigged this utility so as to
facilitate some of the most basic operations for working with NGINX Unit:

- editing parts of the configuration in a reasonably robust manner; and
- restarting applications

Hopefully this utility will soon become obsolete, but you never know. For now I'm publishing it so maybe someone else
can make use of it too.

## Installation

The utility is set up as a Python package, so one can simply install it using:

    pip install git+https://github.com/goc9000/nuri.git

The command `nuri` will then be available in the context where the package was installed (virtual environment,
system-wide etc).

The package, by design, pulls in no dependencies.

## Usage

To restart an application:

    nuri restart <application>

To edit the configuration interactively (all of it):

    nuri edit

This will load the configuration and spawn a standard CLI text editor (like `nano`) so you can see what you are doing
instead of slinging JSON around in the command line. Some help is provided so that you can correct your work if you
accidentally break the JSON syntax or Unit rejects the changes.

You can also use `nuri edit <path>` to focus on just one section of the configuration.

Only the objects under the `config/` API can be edited using this command. Managing certificates is not implemented yet.
