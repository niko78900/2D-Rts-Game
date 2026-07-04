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
        return load_data_bundle(self.settings.data_root, self.settings.schema_root)

    def validation_summary(self) -> dict[str, int]:
        return self.load_definitions().summary()

    def run(self, max_frames: int | None = None) -> int:
        self.load_definitions()
        return GameRuntime(self.settings).run(max_frames=max_frames)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="House of Wolves Remastered")
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate data files and exit without launching the playable slice.",
    )
    parser.add_argument(
        "--windowed",
        action="store_true",
        help="Launch in a fixed-size window instead of fullscreen.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = GameApp(AppSettings(fullscreen=not args.windowed))
    if args.validate:
        summary = app.validation_summary()
        joined = ", ".join(f"{name}={count}" for name, count in summary.items())
        print(f"House of Wolves scaffold validated: {joined}")
        return 0
    return app.run()
