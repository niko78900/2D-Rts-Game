"""Application shell for validation and the minimal playable slice."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass

from house_of_wolves.core.data import DataBundle, load_data_bundle
from house_of_wolves.core.runtime import GameRuntime
from house_of_wolves.core.settings import AppSettings


@dataclass(slots=True)
class GameApp:
    """Entry point owner for validation and the Pygame runtime."""

    settings: AppSettings

    def load_definitions(self) -> DataBundle:
        """Load game data definitions from disk."""
        return load_data_bundle(self.settings.data_root, self.settings.schema_root)

    def validation_summary(self) -> dict[str, int]:
        """Return a text summary of data validation results."""
        return self.load_definitions().summary()

    def run(self, max_frames: int | None = None) -> int:
        """Run the app or runtime loop until it exits."""
        self.load_definitions()
        return GameRuntime(self.settings).run(max_frames=max_frames)


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for the game entry point."""
    parser = argparse.ArgumentParser(description="House of Wolves Remastered")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate data files and exit without launching the playable slice.",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Launch in borderless windowed mode. This is the default.",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="Launch in fullscreen mode instead of the default borderless window.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line entry point."""
    args = build_parser().parse_args(argv)
    app = GameApp(AppSettings(fullscreen=args.fullscreen and not args.windowed))
    if args.validate:
        summary = app.validation_summary()
        joined = ", ".join(f"{name}={count}" for name, count in summary.items())
        print(f"House of Wolves scaffold validated: {joined}")
        return 0
    return app.run()
