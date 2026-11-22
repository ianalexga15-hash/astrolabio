"""Modelos de investigación sobre BTC diario, entrenados en CPU con PyTorch:

1. Redes recurrentes: LSTM, GRU y LSTM bidireccional sobre ventanas de 20 sesiones, más una MLP con Swish, AdamW y
   ReduceLROnPlateau. Se comparan con el pronóstico cero y con Ridge.
2. Autoencoders: PCA de 3 componentes como referencia lineal, un autoencoder y uno con ruido (denoising). Se mide la
   reconstrucción y la utilidad de los 3 factores latentes para pronosticar con Ridge.
3. Modelos generativos: un VAE condicional y una GAN condicional que generan ventanas de 16 rendimientos según la
   volatilidad de las 20 sesiones anteriores. Se comparan sus colas con las reales y con un remuestreo simple.
4. Double DQN: un agente que decide al cierre si quedar en efectivo o comprado, con la posición nueva desde la apertura
   siguiente. Se compara con Q-learning tabular, siempre comprado y siempre en efectivo.

TE nunca se toca: la tabla se corta en el último objetivo de VA de la partición del modelo en producción. VA se parte en
dos mitades: la primera elige épocas, arquitecturas y el mejor punto de control; la segunda solo mide. Todo es simulado
en VA, y el bot no usa estos modelos para decidir.

    .venv\\Scripts\\python research\\modelos_avanzados.py
"""
import copy
import json
import random
import sys
import time
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from bot import data, features  # noqa: E402
from bot.metricas_riesgo import metricas_riesgo, var_cvar  # noqa: E402
from research import lab  # noqa: E402

VARIABLES = ['ret', 'dist_sma20', 'dist_ema20', 'vol20', 'rsi14', 'macd_hist', 'bb_pos', 'atr14', 'vol_rel']
LOOKBACK = 20
SEMILLA = 11
COSTO = 0.001  # 0.10 % por lado: comisión de MEXC (0.05 %) más deslizamiento, igual que al elegir la regla en el laboratorio
UMBRAL = 0.0005  # la regla del modelo en producción: comprar si el pronóstico supera 0.05 %
HORIZONTE, LATENTE = 16, 4
SALIDA = RAIZ / 'models' / 'avanzados' / 'resultados.json'


def semillas(s=SEMILLA):
    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)


def tensor(a):
    return torch.as_tensor(np.asarray(a, dtype=np.float32))


# Datos y partición
def particion_del_modelo(ruta=RAIZ / 'models' / 't4-2026-11-12' / 'contrato.json'):
    p = {f['conjunto']: f for f in json.loads(Path(ruta).read_text(encoding='utf-8'))['seleccion']['particion']}
    return dict(fin_tr=p['TR']['ultima_emision'], fin_va=p['VA']['ultima_emision'], ultimo_objetivo_va=p['VA']['ultimo_objetivo'])


def preparar_datos(tabla, fin_tr, fin_va, ultimo_objetivo_va, variables=VARIABLES, lookback=LOOKBACK):
    """Corta antes de TE, calcula variables, arma ventanas y parte por fecha de emisión. El escalado se ajusta solo con TR."""
    corte = tabla[tabla.date <= ultimo_objetivo_va].reset_index(drop=True)  # nada de TE entra ni a los indicadores
    t = data.add_target(features.add_indicators(corte))
    t['gap'] = t.open.shift(-1) / t.close - 1  # del cierre de t a la apertura de t+1: cuenta la posición anterior
    t['intradia'] = t.close.shift(-1) / t.open.shift(-1) - 1  # de la apertura al cierre de t+1: cuenta la posición nueva
    v = features.make_windows(t, variables, lookback)
    emision = np.array(v.emision)
    assert max(v.emision) <= fin_va and max(v.objetivo) <= ultimo_objetivo_va, 'Una ventana llega a TE'
    tr = np.where(emision <= fin_tr)[0]
    va = np.where((emision > fin_tr) & (emision <= fin_va))[0]
    conjuntos = dict(TR=tr, SEL=va[:len(va) // 2], EVAL=va[len(va) // 2:])
    escala = features.Scaler.fit(v.X[tr])
    y_media, y_desv = float(v.y[tr].mean()), float(v.y[tr].std())
    por_fecha = t.set_index('date')
    d = dict(tabla=t, variables=variables, y_media=y_media, y_desv=y_desv)
    for k, idx in conjuntos.items():
        fechas = list(emision[idx])
        d[f'X_{k}'] = escala.transform(v.X[idx])
        d[f'y_{k}'] = v.y[idx]
        d[f'emision_{k}'] = fechas
        d[f'gap_{k}'] = por_fecha.loc[fechas, 'gap'].to_numpy(dtype=float)
        d[f'intradia_{k}'] = por_fecha.loc[fechas, 'intradia'].to_numpy(dtype=float)
    return d


def resumen_datos(d):
    return {k: dict(ejemplos=len(d[f'y_{k}']), desde=d[f'emision_{k}'][0], hasta=d[f'emision_{k}'][-1]) for k in ('TR', 'SEL', 'EVAL')}


# Entrenamiento con parada temprana sobre VA de selección
def entrenar_regresion(red, Xtr, ytr, Xsel, ysel, lr=1e-3, epocas=120, lote=64, paciencia=12, optimizador='adam', decaimiento=0.0, meseta=False):
    semillas()
    clase = torch.optim.AdamW if optimizador == 'adamw' else torch.optim.Adam
    opt = clase(red.parameters(), lr=lr, weight_decay=decaimiento)
    ajuste = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=5, min_lr=1e-5) if meseta else None
    Xtr, ytr, Xsel, ysel = map(tensor, (Xtr, ytr, Xsel, ysel))
    mejor, estado, mejor_epoca, sin_mejora, curva = float('inf'), copy.deepcopy(red.state_dict()), 0, 0, []
    for epoca in range(1, epocas + 1):
        red.train()
        for idx in torch.randperm(len(Xtr)).split(lote):
            opt.zero_grad()
            F.mse_loss(red(Xtr[idx]).squeeze(-1), ytr[idx]).backward()
            opt.step()
        red.eval()
        with torch.no_grad():
            perdida = F.mse_loss(red(Xsel).squeeze(-1), ysel).item()
        curva.append(perdida)
        if ajuste:
            ajuste.step(perdida)
        if perdida < mejor - 1e-7:
            mejor, estado, mejor_epoca, sin_mejora = perdida, copy.deepcopy(red.state_dict()), epoca, 0
        else:
            sin_mejora += 1
            if sin_mejora >= paciencia:
                break
    red.load_state_dict(estado)  # se conservan los pesos de la época con menor error de validación
    return dict(mejor_epoca=mejor_epoca, epocas=len(curva), mse_seleccion=mejor, curva=curva)


def predecir(red, X):
    red.eval()
    with torch.no_grad():
        return red(tensor(X)).squeeze(-1).numpy()


# 1. Redes recurrentes
class Recurrente(nn.Module):
    """Cada ventana empieza con memoria nueva: el estado no se arrastra entre ventanas."""

    def __init__(self, tipo, entradas, oculta=32, bidireccional=False):
        super().__init__()
        self.tipo, self.bidireccional = tipo, bidireccional
        self.rnn = (nn.LSTM if tipo == 'LSTM' else nn.GRU)(entradas, oculta, batch_first=True, bidirectional=bidireccional)
        self.cabeza = nn.Linear(2 * oculta if bidireccional else oculta, 1)

    def forward(self, x):
        _, estado = self.rnn(x)
        h = estado[0] if self.tipo == 'LSTM' else estado  # la LSTM devuelve (h, c); la GRU solo h
        resumen = torch.cat([h[-2], h[-1]], dim=1) if self.bidireccional else h[-1]
        return self.cabeza(resumen)


def mlp_swish(entradas):
    return nn.Sequential(nn.Flatten(), nn.Linear(entradas, 128), nn.SiLU(), nn.Linear(128, 64), nn.SiLU(), nn.Linear(64, 1))


def parametros(red):
    return sum(p.numel() for p in red.parameters())


def evaluar_pronostico(d, nombre, pred_sel, pred_eval, extra=None):
    """Errores en la escala original y la regla del modelo en producción simulada en la mitad de VA que solo mide."""
    velas = lab.velas_de(d['tabla'], d['emision_EVAL'])
    sim = lab.simular(velas, np.asarray(pred_eval) > UMBRAL, COSTO)
    return dict(modelo=nombre, **(extra or {}), seleccion=lab.metricas(d['y_SEL'], pred_sel), medicion=lab.metricas(d['y_EVAL'], pred_eval),
                regla=_sin_tabla(sim))


def _sin_tabla(sim):
    return {k: v for k, v in sim.items() if k != 'tabla'}


def redes_recurrentes(d, epocas=120):
    filas = [evaluar_pronostico(d, 'Pronóstico cero', np.zeros(len(d['y_SEL'])), np.zeros(len(d['y_EVAL'])))]
    for nombre, cols in (('Ridge α=1000, solo rezagos', [0]), ('Ridge α=1000, 9 variables', slice(None))):
        Xtr, Xsel, Xev = (lab.plano(d[f'X_{k}'][:, :, cols]) for k in ('TR', 'SEL', 'EVAL'))
        w, b = lab.ajustar_lineal(Xtr, d['y_TR'], 1000.0)
        filas.append(evaluar_pronostico(d, nombre, Xsel @ w + b, Xev @ w + b))
    escala = lambda p: d['y_media'] + d['y_desv'] * p  # noqa: E731 - de la escala de entrenamiento a rendimiento
    ytr, ysel = (d['y_TR'] - d['y_media']) / d['y_desv'], (d['y_SEL'] - d['y_media']) / d['y_desv']
    entradas = d['X_TR'].shape[2]
    candidatos = (('LSTM', lambda: Recurrente('LSTM', entradas)), ('GRU', lambda: Recurrente('GRU', entradas)),
                  ('LSTM bidireccional', lambda: Recurrente('LSTM', entradas, bidireccional=True)),
                  ('MLP Swish con AdamW y ReduceLROnPlateau', lambda: mlp_swish(LOOKBACK * entradas)))
    for nombre, crear in candidatos:
        semillas()
        red = crear()
        kw = dict(optimizador='adamw', decaimiento=1e-2, meseta=True) if nombre.startswith('MLP') else {}
        t0 = time.time()
        r = entrenar_regresion(red, d['X_TR'], ytr, d['X_SEL'], ysel, epocas=epocas, **kw)
        filas.append(evaluar_pronostico(d, nombre, escala(predecir(red, d['X_SEL'])), escala(predecir(red, d['X_EVAL'])),
                                        dict(parametros=parametros(red), mejor_epoca=r['mejor_epoca'], epocas=r['epocas'], segundos=round(time.time() - t0, 1))))
    redes = [f for f in filas if 'parametros' in f]
    elegida = min(redes, key=lambda f: f['seleccion']['RMSE'])['modelo']
    return dict(filas=filas, elegida_por_validacion=elegida)


# 2. Autoencoders
class Autoencoder(nn.Module):
    def __init__(self, entradas, latente=3):
        super().__init__()
        self.codificador = nn.Sequential(nn.Linear(entradas, 32), nn.ReLU(), nn.Linear(32, latente))
        self.decodificador = nn.Sequential(nn.Linear(latente, 32), nn.ReLU(), nn.Linear(32, entradas))

    def forward(self, x):
        return self.decodificador(self.codificador(x))


def entrenar_autoencoder(Xtr, Xsel, ruido=0.0, epocas=300, lote=64, paciencia=20):
    semillas()
    red = Autoencoder(Xtr.shape[1])
    opt = torch.optim.Adam(red.parameters(), lr=1e-3)
    Xtr, Xsel = tensor(Xtr), tensor(Xsel)
    mejor, estado, mejor_epoca, sin_mejora = float('inf'), copy.deepcopy(red.state_dict()), 0, 0
    for epoca in range(1, epocas + 1):
        red.train()
        for idx in torch.randperm(len(Xtr)).split(lote):
            limpio = Xtr[idx]
            entrada = limpio + ruido * torch.randn_like(limpio)  # con ruido aprende a recuperar la entrada limpia
            opt.zero_grad()
            F.mse_loss(red(entrada), limpio).backward()
            opt.step()
        red.eval()
        with torch.no_grad():
            perdida = F.mse_loss(red(Xsel), Xsel).item()
        if perdida < mejor - 1e-7:
            mejor, estado, mejor_epoca, sin_mejora = perdida, copy.deepcopy(red.state_dict()), epoca, 0
        else:
            sin_mejora += 1
            if sin_mejora >= paciencia:
                break
    red.load_state_dict(estado)
    return red, dict(mejor_epoca=mejor_epoca, mse_seleccion=mejor)


def autoencoders(d, epocas=300):
    X = {k: d[f'X_{k}'][:, -1, :] for k in ('TR', 'SEL', 'EVAL')}  # las variables del día de emisión, ya escaladas con TR
    _, _, vt = np.linalg.svd(X['TR'] - X['TR'].mean(0), full_matrices=False)
    componentes, centro = vt[:3], X['TR'].mean(0)
    codificar = {'PCA (3 componentes)': lambda A: (A - centro) @ componentes.T}
    reconstruir = {'PCA (3 componentes)': lambda A: (A - centro) @ componentes.T @ componentes + centro}
    entrenamiento = {}
    for nombre, ruido in (('Autoencoder', 0.0), ('Autoencoder con ruido (σ = 0.1)', 0.1)):
        red, info = entrenar_autoencoder(X['TR'], X['SEL'], ruido, epocas)
        entrenamiento[nombre] = info
        codificar[nombre] = lambda A, red=red: red.codificador(tensor(A)).detach().numpy()
        reconstruir[nombre] = lambda A, red=red: red(tensor(A)).detach().numpy()
    filas = []
    for nombre in codificar:
        rec = {k: float(((reconstruir[nombre](X[k]) - X[k]) ** 2).mean()) for k in ('SEL', 'EVAL')}
        w, b = lab.ajustar_lineal(codificar[nombre](X['TR']), d['y_TR'], 1.0)  # Ridge α = 1 sobre los 3 factores
        filas.append(dict(modelo=nombre, mse_reconstruccion_seleccion=rec['SEL'], mse_reconstruccion_medicion=rec['EVAL'],
                          ridge_sobre_factores=lab.metricas(d['y_EVAL'], codificar[nombre](X['EVAL']) @ w + b), **entrenamiento.get(nombre, {})))
    w, b = lab.ajustar_lineal(X['TR'], d['y_TR'], 1.0)
    referencia = dict(ridge_9_variables=lab.metricas(d['y_EVAL'], X['EVAL'] @ w + b), cero=lab.metricas(d['y_EVAL'], np.zeros(len(d['y_EVAL']))))
    elegido = min((f for f in filas if f['modelo'] != 'PCA (3 componentes)'), key=lambda f: f['mse_reconstruccion_seleccion'])['modelo']
    return dict(filas=filas, referencia=referencia, elegido_por_validacion=elegido)


# 3. Modelos generativos de escenarios
def ventanas_generativas(d):
    """Ventanas de 16 rendimientos y su condición: el log de la volatilidad de las 20 sesiones previas. Ninguna cruza un corte."""
    t = d['tabla'].dropna(subset=['ret']).reset_index(drop=True)
    r, fechas = t.ret.to_numpy(dtype=float), t.date.to_numpy()
    cortes = dict(TR=('0000', d['emision_TR'][-1]), SEL=(d['emision_SEL'][0], d['emision_SEL'][-1]), EVAL=(d['emision_EVAL'][0], d['emision_EVAL'][-1]))
    salida = {k: ([], []) for k in cortes}
    for i in range(20, len(r) - HORIZONTE + 1):
        inicio, fin = fechas[i], fechas[i + HORIZONTE - 1]
        for k, (a, b) in cortes.items():
            if a <= inicio and fin <= b:
                salida[k][0].append(r[i:i + HORIZONTE])
                salida[k][1].append(np.log(max(np.std(r[i - 20:i], ddof=1), 1e-8)))
    return {k: (np.array(w), np.array(c)) for k, (w, c) in salida.items()}


class VAECondicional(nn.Module):
    def __init__(self):
        super().__init__()
        self.cod = nn.Sequential(nn.Linear(HORIZONTE + 1, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU())
        self.mu, self.logvar = nn.Linear(64, LATENTE), nn.Linear(64, LATENTE)
        self.dec = nn.Sequential(nn.Linear(LATENTE + 1, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(), nn.Linear(64, HORIZONTE))

    def forward(self, x, c, eps=None):
        h = self.cod(torch.cat([x, c], 1))
        mu, lv = self.mu(h), self.logvar(h).clamp(-8, 8)
        z = mu + torch.exp(0.5 * lv) * (torch.randn_like(mu) if eps is None else eps)  # reparametrización
        return self.generar(z, c), mu, lv

    def generar(self, z, c):
        return self.dec(torch.cat([z, c], 1))


def perdida_vae(x, rec, mu, lv, beta=0.01):
    kl = 0.5 * (mu.square() + lv.exp() - 1 - lv).sum(1).mean()
    return F.mse_loss(rec, x) + beta * kl  # el término KL evita que solo aprenda a copiar


def generador_gan():
    return nn.Sequential(nn.Linear(LATENTE + 1, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(), nn.Linear(64, HORIZONTE))


def discriminador_gan():
    return nn.Sequential(nn.Linear(HORIZONTE + 1, 64), nn.LeakyReLU(0.2), nn.Linear(64, 64), nn.LeakyReLU(0.2), nn.Linear(64, 1))


def estadisticas_escenarios(w):
    acumulado = np.prod(1 + w, axis=1) - 1
    var_d, cvar_d = var_cvar(w.ravel())
    var_a, cvar_a = var_cvar(acumulado)
    return dict(desviacion_diaria=float(w.std()), var95_diario=var_d, cvar95_diario=cvar_d, media_16_dias=float(acumulado.mean()),
                desviacion_16_dias=float(acumulado.std()), var95_16_dias=var_a, cvar95_16_dias=cvar_a, escenarios=len(w))


def generativos(d, epocas_vae=300, epocas_gan=400, por_condicion=20):
    datos = ventanas_generativas(d)
    w_tr, c_tr = datos['TR']
    rm, rs, cm, cs = w_tr.mean(), w_tr.std(), c_tr.mean(), c_tr.std()  # una escala para retornos y otra para la condición
    esc = {k: (tensor((w - rm) / rs), tensor((c - cm) / cs)[:, None]) for k, (w, c) in datos.items()}
    deshacer = lambda x: x.detach().numpy() * rs + rm  # noqa: E731
    gen = torch.Generator().manual_seed(SEMILLA)
    eps_fijo = torch.randn(len(esc['SEL'][0]), LATENTE, generator=gen)  # ruido fijo: compara épocas sin azar

    semillas()
    vae = VAECondicional()
    opt = torch.optim.Adam(vae.parameters(), lr=1e-3)
    mejor_vae, estado_vae, epoca_vae = float('inf'), None, 0
    for epoca in range(1, epocas_vae + 1):
        vae.train()
        for idx in torch.randperm(len(esc['TR'][0])).split(64):
            x, c = esc['TR'][0][idx], esc['TR'][1][idx]
            opt.zero_grad()
            perdida_vae(x, *vae(x, c)).backward()
            opt.step()
        vae.eval()
        with torch.no_grad():
            p = perdida_vae(esc['SEL'][0], *vae(esc['SEL'][0], esc['SEL'][1], eps_fijo)).item()
        if p < mejor_vae:
            mejor_vae, estado_vae, epoca_vae = p, copy.deepcopy(vae.state_dict()), epoca
    vae.load_state_dict(estado_vae)

    def colas_sel(g):
        with torch.no_grad():
            falsos = deshacer(g(torch.randn(len(esc['SEL'][0]), LATENTE, generator=torch.Generator().manual_seed(SEMILLA)), esc['SEL'][1]))
        real = estadisticas_escenarios(datos['SEL'][0])
        sint = estadisticas_escenarios(falsos)
        return abs(sint['desviacion_diaria'] - real['desviacion_diaria']) + abs(sint['cvar95_diario'] - real['cvar95_diario'])

    semillas()
    g, disc = generador_gan(), discriminador_gan()
    opt_g, opt_d = (torch.optim.Adam(m.parameters(), lr=2e-4, betas=(0.5, 0.999)) for m in (g, disc))
    bce = nn.BCEWithLogitsLoss()
    mejor_gan, estado_gan, epoca_gan = float('inf'), copy.deepcopy(g.state_dict()), 0
    for epoca in range(1, epocas_gan + 1):
        for idx in torch.randperm(len(esc['TR'][0])).split(64):
            x, c = esc['TR'][0][idx], esc['TR'][1][idx]
            falso = g(torch.cat([torch.randn(len(x), LATENTE), c], 1))
            opt_d.zero_grad()  # el discriminador distingue real de sintético
            (bce(disc(torch.cat([x, c], 1)), torch.ones(len(x), 1)) + bce(disc(torch.cat([falso.detach(), c], 1)), torch.zeros(len(x), 1))).backward()
            opt_d.step()
            opt_g.zero_grad()  # el generador intenta convencerlo
            bce(disc(torch.cat([falso, c], 1)), torch.ones(len(x), 1)).backward()
            opt_g.step()
        if epoca % 10 == 0:
            error = colas_sel(lambda z, c: g(torch.cat([z, c], 1)))
            if error < mejor_gan:
                mejor_gan, estado_gan, epoca_gan = error, copy.deepcopy(g.state_dict()), epoca
    g.load_state_dict(estado_gan)

    w_ev, c_ev = esc['EVAL']
    c_rep = c_ev.repeat_interleave(por_condicion, 0)
    z = torch.randn(len(c_rep), LATENTE, generator=torch.Generator().manual_seed(SEMILLA + 1))
    with torch.no_grad():
        escenarios = {'VAE condicional': deshacer(vae.generar(z, c_rep)), 'GAN condicional': deshacer(g(torch.cat([z, c_rep], 1)))}
    rng = np.random.default_rng(SEMILLA)
    escenarios['Remuestreo de días de TR'] = rng.choice(w_tr.ravel(), size=(len(c_rep), HORIZONTE))
    real = estadisticas_escenarios(datos['EVAL'][0])
    filas = [dict(fuente='Ventanas reales de VA', **real, respuesta_a_la_volatilidad=float(np.corrcoef(c_ev.numpy().ravel(), datos['EVAL'][0].std(axis=1))[0, 1]))]
    for nombre, w in escenarios.items():
        sensibilidad = float(np.corrcoef(c_rep.numpy().ravel(), w.std(axis=1))[0, 1]) if nombre != 'Remuestreo de días de TR' else None
        filas.append(dict(fuente=nombre, **estadisticas_escenarios(w), respuesta_a_la_volatilidad=sensibilidad))
    return dict(filas=filas, ventanas={k: len(w) for k, (w, _) in datos.items()}, vae=dict(mejor_epoca=epoca_vae, perdida_seleccion=mejor_vae),
                gan=dict(mejor_epoca=epoca_gan, error_colas_seleccion=mejor_gan))


# 4. Double DQN
def paso_entorno(posicion, accion, gap, intradia, costo=COSTO):
    """Decisión al cierre de t: la posición anterior vive el gap hasta la apertura de t+1, donde se paga el cambio, y la nueva
    vive el intradía. La recompensa es 100 veces el rendimiento neto del patrimonio."""
    factor = (1 + posicion * gap) * (1 - costo * abs(accion - posicion)) * (1 + accion * intradia)
    return factor, 100 * (factor - 1)


def objetivo_double_dqn(q_online_siguiente, q_target_siguiente, recompensa, terminal, gamma):
    """La red online elige la acción del estado siguiente y la red target evalúa esa misma acción."""
    elegida = q_online_siguiente.argmax(1, keepdim=True)
    futuro = q_target_siguiente.gather(1, elegida).squeeze(1)
    return recompensa + gamma * (1 - terminal) * futuro


def red_q(entradas):
    return nn.Sequential(nn.Linear(entradas, 64), nn.ReLU(), nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 2))


def recorrer(politica, estados, gap, intradia):
    """Aplica una política sin aprender. Devuelve el patrimonio diario, con base 1, y las posiciones."""
    posicion, patrimonio, posiciones = 0, [1.0], []
    for t in range(len(estados)):
        accion = politica(estados[t], posicion, t)
        factor, _ = paso_entorno(posicion, accion, gap[t], intradia[t])
        patrimonio.append(patrimonio[-1] * factor)
        posiciones.append(accion)
        posicion = accion
    return np.array(patrimonio), np.array(posiciones)


def evaluar_politica(nombre, patrimonio, posiciones):
    cambios = np.abs(np.diff(np.r_[0, posiciones]))
    return dict(politica=nombre, rendimiento=float(patrimonio[-1] - 1), drawdown=lab.max_drawdown(patrimonio), rotacion=float(cambios.mean()),
                dias_comprado=float(np.mean(posiciones)), **{k: v for k, v in metricas_riesgo(patrimonio).items() if k != 'observaciones'})


def entrenar_ddqn(d, episodios=40, gamma=0.95, buffer=10_000, lote=64, inicio=128, cada=4, sincronizar=100):
    semillas()
    s_tr = d['X_TR'][:, -1, :]
    online = red_q(s_tr.shape[1] + 1)
    target = copy.deepcopy(online)
    opt = torch.optim.Adam(online.parameters(), lr=1e-3)
    memoria = deque(maxlen=buffer)
    total, pasos, actualizaciones = episodios * len(s_tr), 0, 0
    greedy = lambda red: lambda s, p, t: int(red(tensor(np.r_[s, p])[None]).argmax(1).item())  # noqa: E731
    mejor, estado, mejor_episodio = -float('inf'), copy.deepcopy(online.state_dict()), 0
    for episodio in range(1, episodios + 1):
        posicion = 0
        for t in range(len(s_tr) - 1):
            epsilon = max(0.05, 1.0 - 0.95 * pasos / (0.6 * total))  # explora mucho al inicio y menos con los pasos
            s = np.r_[s_tr[t], posicion]
            with torch.no_grad():
                accion = random.randrange(2) if random.random() < epsilon else int(online(tensor(s)[None]).argmax(1).item())
            _, recompensa = paso_entorno(posicion, accion, d['gap_TR'][t], d['intradia_TR'][t])
            terminal = t == len(s_tr) - 2
            memoria.append((s, accion, recompensa, np.r_[s_tr[t + 1], accion], float(terminal)))
            posicion, pasos = accion, pasos + 1
            if len(memoria) >= inicio and pasos % cada == 0:
                s_b, a_b, r_b, ns_b, done_b = map(np.array, zip(*random.sample(memoria, lote)))
                with torch.no_grad():
                    esperado = objetivo_double_dqn(online(tensor(ns_b)), target(tensor(ns_b)), tensor(r_b), tensor(done_b), gamma)
                actual = online(tensor(s_b)).gather(1, torch.as_tensor(a_b)[:, None]).squeeze(1)
                opt.zero_grad()
                F.smooth_l1_loss(actual, esperado).backward()
                nn.utils.clip_grad_norm_(online.parameters(), 1.0)
                opt.step()
                actualizaciones += 1
                if actualizaciones % sincronizar == 0:
                    target.load_state_dict(online.state_dict())
        online.eval()
        with torch.no_grad():
            patrimonio, _ = recorrer(greedy(online), d['X_SEL'][:, -1, :], d['gap_SEL'], d['intradia_SEL'])
        online.train()
        if patrimonio[-1] > mejor:  # se guarda el mejor punto de control según la mitad de VA que elige
            mejor, estado, mejor_episodio = patrimonio[-1], copy.deepcopy(online.state_dict()), episodio
    online.load_state_dict(estado)
    online.eval()
    return online, dict(episodios=episodios, mejor_episodio=mejor_episodio, rendimiento_seleccion=float(mejor - 1), actualizaciones=actualizaciones)


def estado_tabular(s, posicion, variables=VARIABLES):
    """Q-learning tabular: RSI en tres zonas, precio sobre o bajo su SMA20, y posición. Usa los valores escalados con TR."""
    rsi, dist = s[variables.index('rsi14')], s[variables.index('dist_sma20')]
    return (0 if rsi < -0.75 else 2 if rsi > 0.75 else 1) * 4 + (dist > 0) * 2 + posicion


def entrenar_q_tabular(d, episodios=40, alfa=0.1, gamma=0.95):
    semillas()
    q = np.zeros((12, 2))
    s_tr = d['X_TR'][:, -1, :]
    total, pasos = episodios * len(s_tr), 0
    for _ in range(episodios):
        posicion = 0
        for t in range(len(s_tr) - 1):
            e = estado_tabular(s_tr[t], posicion)
            epsilon = max(0.05, 1.0 - 0.95 * pasos / (0.6 * total))
            accion = random.randrange(2) if random.random() < epsilon else int(q[e].argmax())
            _, recompensa = paso_entorno(posicion, accion, d['gap_TR'][t], d['intradia_TR'][t])
            siguiente = estado_tabular(s_tr[t + 1], accion)
            q[e, accion] += alfa * (recompensa + gamma * q[siguiente].max() - q[e, accion])
            posicion, pasos = accion, pasos + 1
    return q


def agente_double_dqn(d, episodios=40):
    t0 = time.time()
    online, info = entrenar_ddqn(d, episodios)
    q = entrenar_q_tabular(d, episodios)
    s_ev = d['X_EVAL'][:, -1, :]
    politicas = {
        'Double DQN': lambda s, p, t: int(online(tensor(np.r_[s, p])[None]).argmax(1).item()),
        'Q-learning tabular': lambda s, p, t: int(q[estado_tabular(s, p)].argmax()),
        'Siempre comprado': lambda s, p, t: 1,
        'Siempre en efectivo': lambda s, p, t: 0,
    }
    with torch.no_grad():
        filas = [evaluar_politica(n, *recorrer(f, s_ev, d['gap_EVAL'], d['intradia_EVAL'])) for n, f in politicas.items()]
    return dict(filas=filas, entrenamiento=info | dict(segundos=round(time.time() - t0, 1)))


def _redondear(x):
    if isinstance(x, float):
        return None if not np.isfinite(x) else round(x, 8)
    if isinstance(x, dict):
        return {k: _redondear(v) for k, v in x.items() if k != 'curva'}
    if isinstance(x, (list, tuple)):
        return [_redondear(v) for v in x]
    if isinstance(x, np.generic):
        return _redondear(x.item())
    return x


def main():
    inicio = time.time()
    p = particion_del_modelo()
    d = preparar_datos(pd.read_csv(RAIZ / 'data' / 'processed' / 'BTCUSDT_1d.csv'), **p)
    print('Datos:', resumen_datos(d), flush=True)
    resultados = dict(generado=time.strftime('%Y-%m-%d %H:%M:%S'), dispositivo='cpu', semilla=SEMILLA, activo='BTCUSDT', variables=VARIABLES,
                      lookback=LOOKBACK, costo_por_lado=COSTO, umbral_regla=UMBRAL, particion=p, conjuntos=resumen_datos(d), estado='Simulado en VA; TE no se usó')
    for clave, funcion in (('recurrentes', redes_recurrentes), ('autoencoders', autoencoders), ('generativos', generativos), ('agente', agente_double_dqn)):
        t0 = time.time()
        resultados[clave] = funcion(d)
        print(f'{clave}: {time.time() - t0:.0f} s', flush=True)
    resultados['segundos'] = round(time.time() - inicio)
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(_redondear(resultados), indent=1, ensure_ascii=False), encoding='utf-8')
    print('Guardado en', SALIDA.relative_to(RAIZ))


if __name__ == '__main__':
    main()
