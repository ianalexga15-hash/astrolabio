"""Cada instrumento activo debe tener identidad local; SVG sin contenido ejecutable/remoto."""
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_universo_tiene_logo_local_y_registro_del_panel():
    universo = json.loads((RAIZ / 'config/universo.json').read_text(encoding='utf-8'))['simbolos']
    fuentes = json.loads((RAIZ / 'frontend/public/activos/fuentes.json').read_text(encoding='utf-8'))
    por_simbolo = {f['simbolo']: f for f in fuentes}
    registro = (RAIZ / 'frontend/src/identidadActivos.ts').read_text(encoding='utf-8')
    for simbolo in universo:
        assert simbolo in por_simbolo, f'Falta imagen identificativa de {simbolo}'
        f = por_simbolo[simbolo]
        assert f'"{simbolo.removesuffix("USDT")}": {{ archivo: "{f["archivo"]}"' in registro
        assert (RAIZ / 'frontend/public/activos' / f['archivo']).is_file()


def test_svg_locales_no_ejecutan_codigo_ni_cargan_recursos_externos():
    carpeta = RAIZ / 'frontend/public/activos'
    for ruta in [*carpeta.glob('*.svg'), RAIZ / 'frontend/public/astrolabio.svg']:
        texto = ruta.read_text(encoding='utf-8-sig')
        for nodo in ET.fromstring(texto).iter():
            assert nodo.tag.split('}')[-1] not in ('script', 'foreignObject', 'image'), ruta.name
            for atributo, valor in nodo.attrib.items():
                assert not atributo.lower().startswith('on'), ruta.name
                if atributo.endswith('href'):
                    assert valor.startswith('#'), ruta.name
        for url in re.findall(r'url\(\s*[\"\x27]?([^\)\"\x27]+)', texto):
            assert url.startswith('#'), ruta.name
