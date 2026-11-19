"""Datos sintéticos para pruebas: mismo formato que devuelve MEXC."""
import numpy as np

DAY = 86_400_000
START = 1_600_000_000_000 - (1_600_000_000_000 % DAY)


def rows(closes, start=START, volume=10.0):
    out = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i else c
        out.append([start + i * DAY, str(o), str(max(o, c) * 1.01), str(min(o, c) * 0.99), str(c),
                    str(volume), start + (i + 1) * DAY, str(volume * c)])
    return out


def random_walk(n, seed=0, first=100.0, sigma=0.02):
    rng = np.random.default_rng(seed)
    return (first * np.cumprod(1 + rng.normal(0, sigma, n))).round(4).tolist()
