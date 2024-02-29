from pathlib import Path


def main(im_path: Path) -> None:
    with open(im_path, "rb") as inp:
        file = inp.read()

    # this is the byte string in the function `create_icon`
    print(file)


if __name__ == "__main__":
    path = Path(__file__).parent.parent / "icons" / "zoo-icon_16x16.png"
    main(path)
