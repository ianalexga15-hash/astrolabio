"""Crea assets/astrolabio.ico para el acceso de Windows. Mismo dibujo que frontend/public/astrolabio.svg."""
from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parent.parent
ESCALA = 4
LADO = 256 * ESCALA


def e(*valores):
    return [v * ESCALA for v in valores]


def degradado_radial():
    interior, exterior = (34, 48, 110), (9, 12, 32)
    img = Image.new('RGB', (256, 256))
    px = img.load()
    for y in range(256):
        for x in range(256):
            t = min(1.0, (((x - 128) ** 2 + (y - 108) ** 2) ** 0.5) / 158)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(interior, exterior))
    return img.resize((LADO, LADO), Image.Resampling.BICUBIC)


def anillo(d, cx, cy, r, ancho, color):
    d.ellipse(e(cx - r, cy - r, cx + r, cy + r), outline=color, width=ancho * ESCALA)


def dibujar():
    fondo = degradado_radial().convert('RGBA')
    d = ImageDraw.Draw(fondo)
    laton, claro, azul, azul_tenue = (240, 194, 110, 255), (255, 226, 166, 255), (124, 196, 255, 255), (86, 132, 182, 255)
    anillo(d, 128, 128, 110, 7, laton)
    for (x0, y0, x1, y1) in ((128, 26, 128, 39), (128, 217, 128, 230), (26, 128, 39, 128), (217, 128, 230, 128), (56, 56, 65, 65), (191, 191, 200, 200), (200, 56, 191, 65), (65, 191, 56, 200)):
        d.line(e(x0, y0, x1, y1), fill=(245, 205, 134, 255), width=4 * ESCALA)
    anillo(d, 128, 118, 62, 4, azul)
    anillo(d, 128, 150, 42, 3, azul_tenue)
    d.polygon(e(120, 120, 180, 76, 136, 136), fill=laton)  # aguja que apunta a la estrella
    d.polygon(e(120, 120, 92, 164, 136, 136), fill=(185, 138, 62, 255))
    d.ellipse(e(117, 117, 139, 139), fill=claro)
    d.ellipse(e(124, 124, 132, 132), fill=(10, 14, 31, 255))
    d.polygon(e(190, 48, 194.5, 61.5, 208, 66, 194.5, 70.5, 190, 84, 185.5, 70.5, 172, 66, 185.5, 61.5), fill=(255, 255, 255, 255))
    for cx, cy, r in ((86, 96, 4.5), (106, 182, 3.5), (176, 160, 3.5)):
        d.ellipse(e(cx - r, cy - r, cx + r, cy + r), fill=(207, 230, 255, 255))
    mascara = Image.new('L', (LADO, LADO), 0)
    ImageDraw.Draw(mascara).ellipse(e(4, 4, 252, 252), fill=255)
    salida = Image.new('RGBA', (LADO, LADO), (0, 0, 0, 0))
    salida.paste(fondo, (0, 0), mascara)
    return salida.resize((256, 256), Image.Resampling.LANCZOS)


def main():
    carpeta = RAIZ / 'assets'
    carpeta.mkdir(exist_ok=True)
    img = dibujar()
    img.save(carpeta / 'astrolabio.png')
    img.save(carpeta / 'astrolabio.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print('Icono creado en', carpeta)


if __name__ == '__main__':
    main()
