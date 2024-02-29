from pathlib import Path

from PIL import Image


def main(im_path: Path, new_size: tuple[int, int]) -> None:
    im = Image.open(im_path)
    resized = im.resize(new_size)
    save_path = im_path.parent / f"{im_path.stem}_{new_size[0]}x{new_size[1]}.png"
    resized.save(save_path)


if __name__ == "__main__":
    path = Path(__file__).parent.parent / "icons" / "zoo-icon.png"
    size = (16, 16)
    main(path, size)
