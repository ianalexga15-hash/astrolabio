"""Exporta los registros del bot a CSV: corridas, decisiones, órdenes, patrimonio, errores y configuración.

Solo lee la base, así que puede correr con el bot encendido. Nunca exporta la huella de la contraseña.

    python scripts/exportar_registros.py
    python scripts/exportar_registros.py --salida output/registros/copia
"""
import argparse
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from bot.config import cargar_ajustes  # noqa: E402
from bot.report import exportar_registros  # noqa: E402


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--salida', default=str(RAIZ / 'output' / 'registros' / date.today().isoformat()))
    args = a.parse_args()
    resumen = exportar_registros(cargar_ajustes().db, args.salida)
    for tabla, n in resumen.items():
        print(f'{tabla}: {n} filas')
    print('Listo en', args.salida)


if __name__ == '__main__':
    main()
