from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1] / "output" / "trackside_card_library_v1"
SOURCE = ROOT / "source_png"
TARGET = ROOT / "trackside_card_library_review.png"


def checkerboard(size, cell=24):
    image = Image.new("RGB", size, "#22262b")
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            draw.rectangle(
                (x, y, x + cell - 1, y + cell - 1),
                fill="#30363d" if (x // cell + y // cell) % 2 else "#252a30",
            )
    return image


def place(canvas, path, box, label):
    sprite = Image.open(path).convert("RGBA")
    sprite.thumbnail((box[2], box[3] - 34), Image.Resampling.LANCZOS)
    x = box[0] + (box[2] - sprite.width) // 2
    y = box[1] + 30 + (box[3] - 34 - sprite.height) // 2
    canvas.paste(sprite, (x, y), sprite)
    draw = ImageDraw.Draw(canvas)
    draw.text((box[0] + 8, box[1] + 7), label, fill="#f1f5f9", font=ImageFont.load_default())
    draw.rectangle((box[0], box[1], box[0] + box[2] - 1, box[1] + box[3] - 1), outline="#64748b", width=2)


def main():
    canvas = checkerboard((1920, 1640))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1920, 86), fill="#111827")
    draw.text((36, 24), "TRACKSIDE CARD LIBRARY V1 — 10 PEOPLE / 5 FICTIONAL 90s ADS", fill="white", font=ImageFont.load_default())
    for index in range(10):
        col, row = index % 5, index // 5
        place(canvas, SOURCE / f"person_{index + 1:02d}.png", (35 + col * 370, 110 + row * 500, 350, 470), f"PERSON {index + 1:02d} — 1.8 m")
    signs = sorted(SOURCE.glob("sign_*.png"))
    for index, path in enumerate(signs):
        col, row = index % 3, index // 3
        place(canvas, path, (35 + col * 620, 1080 + row * 270, 600, 240), f"SIGN {index + 1:02d} — 3.6 m wide")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(TARGET, optimize=True)
    print(TARGET)


if __name__ == "__main__":
    main()
