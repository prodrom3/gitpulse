"""Subcommand modules for gitpulse.

Each module in this package defines two callables:
- add_parser(subparsers): register the subparser for the command
- run(args) -> int: execute the command and return a process exit code
"""
