"""El acceso del escritorio y el arranque automático: servidor en segundo plano, ventana solo si se pide."""
from bot import lanzar


def preparar(monkeypatch, tmp_path, corre):
    (tmp_path / '.env').write_text('x', encoding='utf-8')
    (tmp_path / 'frontend' / 'dist').mkdir(parents=True)
    (tmp_path / 'frontend' / 'dist' / 'index.html').write_text('x', encoding='utf-8')
    monkeypatch.setattr(lanzar, 'RAIZ', tmp_path)
    estado = dict(corre=corre, arranques=0, ventanas=0, avisos=[], ollama=0)

    class Proceso:
        def poll(self):
            return None

    def arrancar():
        estado['arranques'] += 1
        estado['corre'] = True
        return Proceso()

    monkeypatch.setattr(lanzar, 'corriendo', lambda: estado['corre'])
    monkeypatch.setattr(lanzar, 'arrancar', arrancar)
    monkeypatch.setattr(lanzar, 'abrir_ventana', lambda: estado.__setitem__('ventanas', estado['ventanas'] + 1))
    monkeypatch.setattr(lanzar, 'avisar', estado['avisos'].append)
    monkeypatch.setattr(lanzar, 'asegurar_ollama', lambda: estado.__setitem__('ollama', estado['ollama'] + 1))
    return estado


def test_sin_ventana_arranca_el_servidor_y_no_abre_el_panel(monkeypatch, tmp_path):
    e = preparar(monkeypatch, tmp_path, corre=False)
    lanzar.main(ventana=False)
    assert e['arranques'] == 1 and e['ventanas'] == 0 and not e['avisos']
    assert e['ollama'] == 1  # al desbloquear la laptop vuelven el bot y su LLM local


def test_con_el_servidor_ya_corriendo_solo_abre_el_panel(monkeypatch, tmp_path):
    e = preparar(monkeypatch, tmp_path, corre=True)
    lanzar.main()
    assert e['arranques'] == 0 and e['ventanas'] == 1


def ollama(monkeypatch, tmp_path, responde, instalado=True):
    app = tmp_path / 'ollama app.exe'
    if instalado:
        app.write_text('x', encoding='utf-8')
    lanzados = []
    monkeypatch.setattr(lanzar, 'OLLAMA_APP', app)
    monkeypatch.setattr(lanzar, 'ollama_responde', lambda: responde)
    monkeypatch.setattr(lanzar.subprocess, 'Popen', lambda args, **k: lanzados.append(args))
    return app, lanzados


def test_si_ollama_no_responde_abre_su_aplicacion(monkeypatch, tmp_path):
    app, lanzados = ollama(monkeypatch, tmp_path, responde=False)
    assert lanzar.asegurar_ollama() is True and lanzados == [[str(app)]]


def test_si_ollama_ya_responde_no_lo_toca(monkeypatch, tmp_path):
    _, lanzados = ollama(monkeypatch, tmp_path, responde=True)
    assert lanzar.asegurar_ollama() is False and not lanzados


def test_sin_ollama_instalado_no_intenta_abrirlo(monkeypatch, tmp_path):
    _, lanzados = ollama(monkeypatch, tmp_path, responde=False, instalado=False)
    assert lanzar.asegurar_ollama() is False and not lanzados
