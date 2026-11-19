"""Notas del desarrollo desde la terminal. Claude, Codex o Alex registran aquí cada paso.

    python scripts/nota.py estado
    python scripts/nota.py agregar --origen claude --tipo Código --galaxia Datos --titulo "..." --texto "..." [--fuente f] [--id x]
"""
import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding='utf-8')

from bot import notes  # noqa: E402

CARPETA = RAIZ / 'notas'


def estado():
    r = notes.resumen(CARPETA)
    for titulo, clave in (('Visión', 'vision'), ('En curso', 'en_curso'), ('Pendiente', 'pendiente'), ('Lo último hecho', 'hecho')):
        print(f'\n{titulo}:')
        for n in r[clave]:
            print(f'  [{n["origen"]}] {n["titulo"]} ({n["fecha"]})')
        if not r[clave]:
            print('  Nada por ahora.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='comando', required=True)
    sub.add_parser('estado')
    a = sub.add_parser('agregar')
    a.add_argument('--origen', required=True, choices=notes.ORIGENES)
    a.add_argument('--tipo', required=True, choices=notes.TIPOS)
    a.add_argument('--galaxia', required=True)
    a.add_argument('--titulo', required=True)
    a.add_argument('--texto', required=True)
    a.add_argument('--fuente', default='')
    a.add_argument('--fecha')
    a.add_argument('--id', help='Actualiza la nota con ese identificador')
    args = p.parse_args()
    if args.comando == 'estado':
        estado()
    else:
        ruta = notes.guardar(CARPETA, args.titulo, args.texto, args.origen, args.tipo, args.galaxia, args.fuente, args.fecha, args.id)
        print(f'Guardada: {ruta.name}')


if __name__ == '__main__':
    main()
