# coding=utf-8

import sys
import argparse

from .errors import UsageError
from . import commands
from .commands import Command


def _iter_command_classes():
    for obj in vars(commands).values():
        if isinstance(obj, type) and issubclass(obj, Command) and obj is not Command:
            yield obj


def _get_commands_from_module():
    d = {}
    for cmd in _iter_command_classes():
        o = cmd()
        if o.name:
            d[o.name] = o
    return d


def _print_commands():
    print("usage: xpaw <command> [options] [args]\n")
    print("available commands:")
    cmds = _get_commands_from_module()
    for cmdname, cmdclass in sorted(cmds.items()):
        print("  {:<10} {}".format(cmdname, cmdclass.short_desc))
    print()
    print('Use "xpaw <command> -h" to see more info about a command')


def _print_unknown_command(cmdname):
    print("Unknown command: %s\n" % cmdname)
    print('Use "xpaw" to see available commands')


def main(argv=None):
    if argv is None:
        argv = sys.argv
    cmds = _get_commands_from_module()
    cmdname = argv[1] if len(argv) > 1 else None
    if not cmdname:
        _print_commands()
        sys.exit(0)
    elif cmdname not in cmds:
        _print_unknown_command(cmdname)
        sys.exit(2)
    del argv[1]
    cmd = cmds[cmdname]
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.usage = "xpaw {} {}".format(cmdname, cmd.syntax)
    parser.description = cmd.long_desc
    cmd.add_arguments(parser)
    try:
        args = parser.parse_args(args=argv[1:])
        cmd.process_arguments(args)
        cmd.run(args)
    except UsageError as e:
        if str(e):
            parser.error(str(e))
        if e.print_help:
            parser.print_help()
        sys.exit(2)
    except Exception as e:
        if str(e):
            parser.error(str(e))
        sys.exit(3)
    else:
        if cmd.exitcode:
            sys.exit(cmd.exitcode)
