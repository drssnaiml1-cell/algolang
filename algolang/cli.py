"""Console entry point: the `algo` command installed by pip."""
import sys

from algolang import HOME  # noqa: F401  (puts the engine folder on sys.path)


def main(argv=None):
    import algoc
    try:
        return algoc.main(argv)
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
