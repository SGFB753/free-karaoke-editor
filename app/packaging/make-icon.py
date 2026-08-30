"""Build the EXE and browser icons from the high-resolution artwork."""

from pathlib import Path

from PIL import Image, ImageFilter


HERE = Path(__file__).resolve().parent
APP = HERE.parent
ART = HERE / "KaraokeStudio-source.png"


def fitted_master() -> Image.Image:
    image = Image.open(ART).convert("RGBA")
    if image.getchannel("A").getbbox() is None:
        raise RuntimeError("icon artwork is empty")
    return image.resize((1024, 1024), Image.Resampling.LANCZOS)


def resized(master: Image.Image, size: int) -> Image.Image:
    image = master.resize((size, size), Image.Resampling.LANCZOS)
    if size <= 64:
        image = image.filter(ImageFilter.UnsharpMask(radius=0.7, percent=135,
                                                     threshold=2))
    return image


def main() -> None:
    master = fitted_master()
    master.save(HERE / "KaraokeStudio-source.png", optimize=True)
    resized(master, 512).save(APP / "kstudio" / "icon.png", optimize=True)
    resized(master, 32).save(APP / "kstudio" / "icon-32.png", optimize=True)
    ico = HERE / "KaraokeStudio.ico"
    master.save(ico, format="ICO", sizes=[(16, 16), (24, 24), (32, 32),
                                          (48, 48), (64, 64), (128, 128),
                                          (256, 256)])
    (APP / "kstudio" / "favicon.ico").write_bytes(ico.read_bytes())


if __name__ == "__main__":
    main()
