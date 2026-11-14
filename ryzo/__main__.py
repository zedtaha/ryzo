import sys


def main():
    from ryzo.core.main import run

    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
