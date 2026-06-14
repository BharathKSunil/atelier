"""Unified CLI: `atelier <command> [args]` (also `python -m atelier`).

Each subcommand delegates to a module main(): the pipeline phases, the server,
and the demo seeder. Run `atelier <cmd> --help` for that command's flags.
"""
import importlib
import sys

COMMANDS = {
    "index": "atelier.pipeline.index",
    "cluster": "atelier.pipeline.cluster",
    "series": "atelier.pipeline.series",
    "score": "atelier.pipeline.score",
    "serve": "atelier.server",
    "demo": "atelier.demo_seed",
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        print("usage: atelier {index|cluster|series|score|serve|demo} [args]\n"
              "  index <--photos DIR --db DB>   detect + embed faces (resumable)\n"
              "  cluster <--db DB>              group faces into people\n"
              "  series  <--db DB>              group photos into bursts\n"
              "  score   <--db DB>              quality scores + best picks\n"
              "  serve   [--port N]             web UI (default ~/.atelier)\n"
              "  demo    [--projects-dir DIR]   seed a synthetic demo project")
        sys.exit(0 if argv and argv[0] in ("-h", "--help") else 1)
    cmd, rest = argv[0], argv[1:]
    mod = importlib.import_module(COMMANDS[cmd])
    sys.argv = [f"atelier {cmd}", *rest]
    mod.main()


if __name__ == "__main__":
    main()
