import pytest

from bot import notes


def escribir(carpeta, **kw):
    base = dict(titulo='Una nota', cuerpo='Texto', origen='claude', tipo='Código', galaxia='Datos', fuente='bot/data.py', fecha='2026-11-05T08:00')
    base.update(kw)
    return notes.guardar(carpeta, **base)


def test_guardar_crea_markdown_con_datos_y_lo_lee_de_vuelta(tmp_path):
    ruta = escribir(tmp_path, titulo='Ingesta de velas', cuerpo='Paginación por ventanas.')
    assert ruta.suffix == '.md'
    n = notes.leer(tmp_path)[0]
    assert (n['titulo'], n['origen'], n['tipo'], n['galaxia'], n['fuente'], n['fecha']) == (
        'Ingesta de velas', 'claude', 'Código', 'Datos', 'bot/data.py', '2026-11-05T08:00')
    assert n['cuerpo'] == 'Paginación por ventanas.'


def test_enlaces_salen_de_doble_corchete_sin_inventar_relaciones(tmp_path):
    escribir(tmp_path, titulo='A', cuerpo='Ver [[B]] y [[No existe]].')
    escribir(tmp_path, titulo='B', cuerpo='Sin enlaces.')
    grafo = notes.grafo(tmp_path)
    ids = {n['titulo']: n['id'] for n in grafo['notas']}
    assert grafo['enlaces'] == [{'origen': ids['A'], 'destino': ids['B']}]


def test_enlaces_ignoran_mayusculas_y_no_enlazan_consigo_misma(tmp_path):
    escribir(tmp_path, titulo='Modelo LSTM', cuerpo='[[modelo lstm]] y [[OTRA NOTA]]')
    escribir(tmp_path, titulo='Otra nota', cuerpo='x')
    grafo = notes.grafo(tmp_path)
    assert len(grafo['enlaces']) == 1


def test_grafo_agrupa_galaxias_y_cuenta_autores(tmp_path):
    escribir(tmp_path, titulo='A', galaxia='Datos', origen='codex')
    escribir(tmp_path, titulo='B', galaxia='Riesgo', origen='claude')
    escribir(tmp_path, titulo='C', galaxia='Riesgo', origen='alex')
    grafo = notes.grafo(tmp_path)
    assert grafo['galaxias'] == {'Datos': 1, 'Riesgo': 2}
    assert grafo['autores'] == {'alex': 1, 'claude': 1, 'codex': 1}


@pytest.mark.parametrize('texto', ['clave: sk-ant-abcdefghijklmnopqrstuvwx', 'password = hunter2222',
                                   'token ghp_abcdefghijklmnopqrstuvwxyz0123456789', '-----BEGIN RSA PRIVATE KEY-----',
                                   'BOT_ADMIN_KEY=abcdef123456', 'MEXC_API_SECRET=abcdef123456', 'mx0v' + 'glA1b2C3d4E5f6g7'])
def test_rechaza_textos_con_secretos(tmp_path, texto):
    with pytest.raises(ValueError, match='secreto'):
        escribir(tmp_path, cuerpo=texto)
    assert not list(tmp_path.glob('*.md'))


@pytest.mark.parametrize('campo,valor', [('origen', 'desconocido'), ('tipo', 'Otro'), ('titulo', ''), ('cuerpo', ''), ('fecha', 'ayer'),
                                           ('ident', '../AGENTS'), ('ident', 'C:/Users/x/CLAUDE')])
def test_rechaza_campos_invalidos(tmp_path, campo, valor):
    with pytest.raises(ValueError):
        escribir(tmp_path, **{campo: valor})


def test_titulo_repetido_se_rechaza_para_no_romper_enlaces(tmp_path):
    escribir(tmp_path, titulo='Igual')
    with pytest.raises(ValueError, match='Ya existe'):
        escribir(tmp_path, titulo='igual')


def test_actualizar_misma_nota_por_identificador(tmp_path):
    ruta = escribir(tmp_path, titulo='En curso', tipo='En curso')
    notes.guardar(tmp_path, titulo='En curso', cuerpo='Terminado', origen='claude', tipo='Código', galaxia='Datos', fuente='', fecha='2026-11-05T09:00', ident=ruta.stem)
    leidas = notes.leer(tmp_path)
    assert len(leidas) == 1 and leidas[0]['tipo'] == 'Código' and leidas[0]['cuerpo'] == 'Terminado'


def test_nombre_de_archivo_es_seguro_aunque_el_titulo_tenga_rutas(tmp_path):
    ruta = escribir(tmp_path, titulo='../../fuera: de la carpeta?')
    assert ruta.parent == tmp_path and ruta.exists()


def test_archivo_mal_formado_se_omite_e_informa(tmp_path):
    (tmp_path / 'roto.md').write_text('sin encabezado', encoding='utf-8')
    escribir(tmp_path, titulo='Buena')
    grafo = notes.grafo(tmp_path)
    assert [n['titulo'] for n in grafo['notas']] == ['Buena']
    assert grafo['omitidas'] == ['roto.md']


def test_estado_resume_vision_en_curso_pendiente_y_ultimo(tmp_path):
    escribir(tmp_path, titulo='V', tipo='Visión', origen='alex')
    escribir(tmp_path, titulo='C', tipo='En curso')
    escribir(tmp_path, titulo='P', tipo='Pendiente')
    escribir(tmp_path, titulo='H', tipo='Código')
    r = notes.resumen(tmp_path)
    assert [n['titulo'] for n in r['vision']] == ['V']
    assert [n['titulo'] for n in r['en_curso']] == ['C']
    assert [n['titulo'] for n in r['pendiente']] == ['P']
    assert [n['titulo'] for n in r['hecho']] == ['H']
