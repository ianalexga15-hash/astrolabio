"""Auditoría del registro CLI con modelos ficticios, sin mercado, LLM ni datos de TE."""
import importlib
import json
from dataclasses import replace
from types import SimpleNamespace
import pytest

from bot.store import Store
from tests.test_risk import L


@pytest.mark.parametrize('cartera', [True, False])
def test_cartera_registra_modelo_real_y_limites_por_activo(tmp_path, monkeypatch, capsys, cartera):
    # El CLI configura su stdout al importar; usar el stream real, no el capturador.
    with capsys.disabled():
        cli = importlib.import_module('research.replay')
    carpeta = tmp_path / 'models'
    carpeta.mkdir()
    (carpeta / 'ACTIVO.txt').write_text('t4-ficticio')
    (carpeta / 'CARTERA.txt').write_text('cartera-ficticia')
    db = tmp_path / 'prueba.sqlite3'
    limites = replace(L, capital_inicial=1000, objetivo_pct=0.13, filtro_minimo='sma20')
    monkeypatch.setattr(cli.sys, 'argv', ['replay.py', '--decisor', 'regla', '--dias', '2'] + (['--cartera'] if cartera else ['--simbolo', 'ETHUSDT']))
    monkeypatch.setattr(cli, 'cargar_ajustes', lambda: SimpleNamespace(raiz=tmp_path, db=db))
    monkeypatch.setattr(cli, 'cargar_limites', lambda *_: limites)
    monkeypatch.setattr(cli, 'cargar_universo', lambda *_: ['BTCUSDT', 'ETHUSDT'])
    monkeypatch.setattr(cli.model, 'cargar', lambda path: SimpleNamespace(version=path.name))
    monkeypatch.setattr(cli, 'fechas_conjunto', lambda _: ['2020-01-01', '2020-01-02'])
    monkeypatch.setattr(cli, 'MercadoFijo', lambda: object())
    ejecutados = []
    monkeypatch.setattr(cli, 'correr', lambda store, lim, modelo, proponente, simbolo, run, fechas, mercado: ejecutados.append((run, modelo.version, lim.capital_inicial, simbolo)))
    monkeypatch.setattr(cli, 'resumen_grupo', lambda *_: {})
    monkeypatch.setattr(cli, 'resumen_run', lambda *_: {})
    cli.main()
    store = Store(db)
    assert len(ejecutados) == (2 if cartera else 1)
    for run, version, cupo, simbolo in ejecutados:
        assert version == ('t4-ficticio' if simbolo == 'BTCUSDT' else 'cartera-ficticia')
        registro = store.run(run)['parametros']
        if isinstance(registro, str):
            registro = json.loads(registro)
        assert registro['modelo'] == version
        assert registro['limites']['capital_inicial'] == cupo == (500 if cartera else 1000)
        assert registro['limites']['objetivo_pct'] == 0.13
        assert registro['limites']['filtro_minimo'] == 'sma20'


class PasoElSello(Exception):
    """El CLI siguió después del sello de TE: la prueba lo detiene antes de leer datos."""


@pytest.mark.parametrize('previa, decisor, rechaza', [
    ('replay-TE-regla-BTCUSDT-1794550224', 'regla', True),
    ('replay-cartera-TE-llm-1794550231:ETHUSDT', 'llm', True),
    ('replay-TE-llm-BTCUSDT-1794550231', 'regla', False),
    ('replay-VA-regla-BTCUSDT-1794550224', 'regla', False),
])
def test_te_se_abre_una_sola_vez_por_decisor(tmp_path, monkeypatch, capsys, previa, decisor, rechaza):
    with capsys.disabled():
        cli = importlib.import_module('research.replay')
    db = tmp_path / 'prueba.sqlite3'
    Store(db).abrir_run(previa, 'replay', 'corrida previa')
    monkeypatch.setattr(cli.sys, 'argv', ['replay.py', '--decisor', decisor, '--conjunto', 'TE', '--confirmo-abrir-te'])
    monkeypatch.setattr(cli, 'cargar_ajustes', lambda: SimpleNamespace(raiz=tmp_path, db=db))

    def pasar(*_):
        raise PasoElSello

    monkeypatch.setattr(cli, 'cargar_limites', pasar)
    with pytest.raises(SystemExit if rechaza else PasoElSello) as error:
        cli.main()
    if rechaza:
        assert 'TE ya se abrió' in str(error.value) and previa in str(error.value)
    assert [r['id'] for r in Store(db).runs()] == [previa]  # la corrida existente se conserva y no se agrega otra
