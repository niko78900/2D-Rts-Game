"""Generate transparent, normalized building sprites from supplied source sheets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "assets" / "art" / "buildings"
OUTPUT_ROOT = SOURCE_ROOT / "processed"


@dataclass(frozen=True, slots=True)
class SpriteMapping:
    building_id: str
    source_folder: str


BUILDING_MAPPINGS = (
    SpriteMapping("hut", "Hut"),
    SpriteMapping("barracks", "Barracks"),
    SpriteMapping("archery", "Archery"),
    SpriteMapping("chicken_farm", "Chicken cop"),
    SpriteMapping("pig_farm", "Pig pen"),
)

STAGE_MAPPINGS = {
    ("Construction", "0 to 50.png"): "construction_0_50.png",
    ("Construction", "50 to 90.png"): "construction_50_90.png",
    ("Construction", "90 to 100.png"): "complete.png",
    ("Destruction", "75 to 50.png"): "damage_75_50.png",
    ("Destruction", "50 to 25.png"): "damage_50_25.png",
    ("Destruction", "25 to 10.png"): "damage_25_10.png",
    ("Destruction", "10 to 0.png"): "destroyed_10_0.png",
}


def main() -> None:
    """Process every known building source image into normalized RGBA sprites."""
    for mapping in BUILDING_MAPPINGS:
        for (stage_folder, source_name), output_name in STAGE_MAPPINGS.items():
            source = SOURCE_ROOT / mapping.source_folder / stage_folder / source_name
            output = OUTPUT_ROOT / mapping.building_id / output_name
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
    cropped_alpha = alpha.crop(padded)
    rgba.putalpha(cropped_alpha)
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
