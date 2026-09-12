"""Create the deterministic synthetic character reference used by Goal 54.

The output is a research fixture, not a product asset. It intentionally uses
strong identity anchors (teal bob hair, crimson round glasses, mustard jacket,
beauty mark) and a simple stable room layout so identity/environment drift can
be scored without copyright or personal-data ambiguity.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw


WIDTH = 1280
HEIGHT = 720


def render_reference() -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), (224, 218, 205))
    draw = ImageDraw.Draw(image)

    # Stable room layout: warm wall, left window, right sofa and plant.
    draw.rectangle((0, 0, WIDTH, 520), fill=(222, 216, 205))
    draw.rectangle((0, 520, WIDTH, HEIGHT), fill=(165, 136, 108))
    draw.rectangle((65, 90, 355, 430), fill=(242, 244, 238), outline=(86, 105, 116), width=10)
    draw.line((210, 90, 210, 430), fill=(86, 105, 116), width=8)
    draw.line((65, 260, 355, 260), fill=(86, 105, 116), width=8)
    draw.rectangle((910, 445, 1230, 650), fill=(94, 100, 113), outline=(66, 69, 80), width=8)
    draw.rectangle((945, 410, 1190, 500), fill=(112, 119, 132))
    draw.rectangle((1110, 300, 1135, 455), fill=(116, 84, 61))
    draw.ellipse((1030, 225, 1120, 340), fill=(68, 116, 77))
    draw.ellipse((1120, 210, 1210, 335), fill=(75, 126, 82))

    # Character torso and mustard jacket.
    draw.ellipse((430, 510, 850, 900), fill=(191, 139, 48))
    draw.polygon([(525, 535), (640, 690), (755, 535), (700, 500), (580, 500)], fill=(48, 87, 118))
    draw.line((640, 520, 640, 715), fill=(146, 96, 32), width=8)

    # Neck and face.
    skin = (205, 159, 126)
    draw.rectangle((585, 430, 695, 545), fill=skin)
    draw.ellipse((500, 160, 780, 500), fill=skin)

    # Teal bob haircut with recognizable silhouette.
    teal = (28, 112, 117)
    dark_teal = (20, 79, 84)
    draw.pieslice((470, 115, 810, 520), 180, 360, fill=teal)
    draw.rectangle((470, 260, 540, 455), fill=teal)
    draw.rectangle((740, 260, 810, 455), fill=teal)
    draw.arc((490, 130, 790, 475), 190, 350, fill=dark_teal, width=12)
    draw.line((640, 145, 615, 265), fill=dark_teal, width=9)

    # Brows/eyes.
    draw.arc((548, 280, 615, 315), 190, 345, fill=(70, 49, 43), width=5)
    draw.arc((665, 280, 732, 315), 195, 350, fill=(70, 49, 43), width=5)
    draw.ellipse((568, 304, 584, 322), fill=(39, 42, 43))
    draw.ellipse((696, 304, 712, 322), fill=(39, 42, 43))

    # Crimson round glasses + bridge.
    crimson = (151, 45, 54)
    draw.ellipse((535, 275, 620, 350), outline=crimson, width=10)
    draw.ellipse((660, 275, 745, 350), outline=crimson, width=10)
    draw.line((620, 310, 660, 310), fill=crimson, width=8)
    draw.line((535, 305, 505, 295), fill=crimson, width=7)
    draw.line((745, 305, 775, 295), fill=crimson, width=7)

    # Nose, mouth, beauty mark below subject-right eye.
    draw.line((640, 315, 625, 372), fill=(152, 111, 88), width=4)
    draw.arc((595, 375, 685, 430), 15, 165, fill=(129, 62, 70), width=5)
    draw.ellipse((721, 354, 731, 364), fill=(58, 49, 45))

    # Distinctive silver triangle earrings.
    silver = (205, 210, 211)
    draw.polygon([(515, 360), (535, 405), (495, 405)], fill=silver)
    draw.polygon([(765, 360), (785, 405), (745, 405)], fill=silver)

    return image


def write_reference(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = render_reference()
    image.save(path, format="PNG", optimize=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic Goal 54 synthetic character fixture.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    digest = write_reference(args.output)
    print(f"REFERENCE_FIXTURE path={args.output} width={WIDTH} height={HEIGHT} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
