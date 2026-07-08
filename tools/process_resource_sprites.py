"""Generate transparent, normalized mine resource sprites from supplied sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "assets" / "art" / "resources" / "Ores"
OUTPUT_ROOT = PROJECT_ROOT / "assets" / "art" / "resources" / "processed"


@dataclass(frozen=True, slots=True)
class ResourceSpriteMapping:
    resource_id: str
    source_folder: str


RESOURCE_MAPPINGS = (
    ResourceSpriteMapping("gold_mine", "Gold"),
    ResourceSpriteMapping("iron_deposit", "Iron"),
    ResourceSpriteMapping("stone_outcrop", "Stone"),
)

STAGE_MAPPINGS = {
    "100 to 75.png": "amount_100_75.png",
    "75 to 25.png": "amount_75_25.png",
    "25 to 0.png": "amount_25_0.png",
}


def main() -> None:
    """Process every known mine source image into normalized RGBA sprites."""
    for mapping in RESOURCE_MAPPINGS:
        for source_name, output_name in STAGE_MAPPINGS.items():
            source = SOURCE_ROOT / mapping.source_folder / source_name
            output = OUTPUT_ROOT / mapping.resource_id / output_name
            output.parent.mkdir(parents=True, exist_ok=True)
            _process_sprite(source, output)
            print(f"{source.relative_to(PROJECT_ROOT)} -> {output.relative_to(PROJECT_ROOT)}")


def _process_sprite(source: Path, output: Path) -> None:
    """Remove baked light/checkerboard background and crop to useful pixels."""
    image = Image.open(source).convert("RGB")
    alpha = _foreground_alpha(image)
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError(f"{source} produced an empty sprite")

    padded = _pad_bounds(bounds, image.size, 12)
    rgba = image.convert("RGBA").crop(padded)
    rgba.putalpha(alpha.crop(padded))
    rgba.save(output)


def _foreground_alpha(image: Image.Image) -> Image.Image:
    """Return an alpha mask that treats neutral light pixels as background."""
    rgb = np.asarray(image, dtype=np.int16)
    max_channel = rgb.max(axis=2)
    min_channel = rgb.min(axis=2)
    neutral_light = (min_channel > 218) & ((max_channel - min_channel) < 34)
    alpha = (~neutral_light).astype(np.uint8) * 255
    mask = Image.fromarray(alpha, mode="L")
    return mask.filter(ImageFilter.MaxFilter(3))


def _pad_bounds(
    bounds: tuple[int, int, int, int],
    image_size: tuple[int, int],
    padding: int,
) -> tuple[int, int, int, int]:
    """Return crop bounds with a transparent safety margin."""
    left, top, right, bottom = bounds
    width, height = image_size
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(width, right + padding),
        min(height, bottom + padding),
    )


if __name__ == "__main__":
    main()
