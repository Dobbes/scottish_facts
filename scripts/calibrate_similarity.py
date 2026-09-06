"""Compatibility wrapper for the CLI calibration utility."""

from scotland_facts.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["calibrate"]))
