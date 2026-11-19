"""Laboratorio: preparación, modelos, evaluación y simulación.

El mismo código corre en el notebook de Colab con T4 y en la laptop con CPU. TE solo se abre con abrir_te.
"""
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from bot import data, features, model

UMBRALES = (0.0005, 0.001, 0.002, 0.004, 0.008)  # definidos antes de mirar VA; positivos y distintos del costo
FILTROS = ('ninguno', 'sma20')
CONJUNTOS_VARIABLES = {
    'rezagos': ['ret'],
    'rezagos_indicadores': ['ret', 'dist_sma20', 'vol20'],
}
CONFIGS_MLP = ({'hu': 16, 'lr': 1e-3}, {'hu': 32, 'lr': 1e-3}, {'hu': 32, 'lr': 3e-4})
CONFIGS_LSTM = ({'hu': 8, 'lr': 1e-3}, {'hu': 16, 'lr': 1e-3}, {'hu': 16, 'lr': 3e-4})
SEMILLAS = (11, 22, 33)


# Métricas
def _plano(a, b):
    a, b = np.asarray(a, dtype=float).reshape(-1), np.asarray(b, dtype=float).reshape(-1)
    if len(a) != len(b):
        raise ValueError(f'y y p deben tener la misma longitud: {len(a)} y {len(b)}.')
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        raise ValueError('y y p deben contener valores finitos.')
    return a, b


def metricas(y, p):
    """Escala original. error = estimado - real. En precisión direccional se excluyen los pares con un cero."""
    y, p = _plano(y, p)
    error = p - y
    validos = (y != 0) & (p != 0)
    largos, cortos = int((p > 0).sum()), int((p < 0).sum())
    denominador = float(((y - y.mean()) ** 2).sum())
    constante = np.std(p) == 0 or np.std(y) == 0
    return dict(MAE=float(np.abs(error).mean()), RMSE=float(np.sqrt((error ** 2).mean())),
                direccional=float((np.sign(y[validos]) == np.sign(p[validos])).mean()) if validos.any() else None,
                R2=1 - float((error ** 2).sum()) / denominador if denominador else None,
                correlacion=None if constante else float(np.corrcoef(y, p)[0, 1]),
                sesgo_modelo=largos / cortos if cortos else None, n=len(y))


def casi_constante(p):
    return bool(np.std(np.asarray(p, dtype=float)) < 1e-5)


def max_drawdown(patrimonio):
    serie = np.asarray(patrimonio, dtype=float)
    picos = np.maximum.accumulate(serie)
    return float(((picos - serie) / picos).max())


# Simulación de la estrategia
def simular(velas, senales, comision, capital=100_000.0):
    """La señal del cierre de t se ejecuta en la apertura de t+1. Solo posición comprada o efectivo."""
    senales = np.asarray(senales, dtype=bool)
    if len(senales) != len(velas):
        raise ValueError(f'{len(senales)} señales para {len(velas)} velas.')
    apertura, cierre = velas.open.to_numpy(dtype=float), velas.close.to_numpy(dtype=float)
    efectivo, cantidad, costos, entrada = float(capital), 0.0, 0.0, 0.0
    resultados, filas = [], []
    for t in range(len(velas)):
        comprar = t > 0 and senales[t - 1]
        ejecucion = None
        if comprar and cantidad == 0:
            nocional = efectivo / (1 + comision)  # incluye el costo al calcular cuánto se puede adquirir
            cantidad = nocional / apertura[t]
            costos += nocional * comision
            entrada, efectivo, ejecucion = efectivo, 0.0, apertura[t]
        elif not comprar and cantidad > 0:
            nocional = cantidad * apertura[t]
            costos += nocional * comision
            efectivo = nocional * (1 - comision)
            resultados.append(efectivo - entrada)
            cantidad, ejecucion = 0.0, apertura[t]
        filas.append(dict(fecha=velas.date.iloc[t], precio_ejecucion=ejecucion, senal=bool(senales[t]), posicion=cantidad,
                          efectivo=efectivo, costos=costos, patrimonio=efectivo + cantidad * cierre[t]))
    if cantidad > 0:  # liquidación final para comparar el cierre del periodo
        nocional = cantidad * cierre[-1]
        costos += nocional * comision
        efectivo = nocional * (1 - comision)
        resultados.append(efectivo - entrada)
        filas[-1] |= dict(precio_ejecucion=cierre[-1], posicion=0.0, efectivo=efectivo, costos=costos, patrimonio=efectivo)
    tabla = pd.DataFrame(filas)
    final = float(tabla.patrimonio.iloc[-1])
    return dict(patrimonio_final=final, rendimiento=final / capital - 1, drawdown=max_drawdown(tabla.patrimonio),
                operaciones=len(resultados), win_rate=float(np.mean([r > 0 for r in resultados])) if resultados else None,
                costos=costos, tabla=tabla)


def comprar_y_mantener(velas, comision, capital=100_000.0):
    """Referencia pasiva desde la misma primera fecha de ejecución y con costos equivalentes."""
    return simular(velas, np.ones(len(velas), dtype=bool), comision, capital)


def elegir_regla(resultados):
    """Mayor rendimiento neto en VA; en empate, menor drawdown."""
    return max(resultados, key=lambda r: (round(r['rendimiento'], 10), -r['drawdown']))


# Partición y preparación
def verificar_particion(fechas_objetivo):
    if not max(fechas_objetivo['TR']) < min(fechas_objetivo['VA']):
        raise ValueError('El último objetivo de TR no es anterior al primero de VA: invalida el experimento.')
    if not max(fechas_objetivo['VA']) < min(fechas_objetivo['TE']):
        raise ValueError('El último objetivo de VA no es anterior al primero de TE: invalida el experimento.')


def folds_expansivos(n_tr, k=3):
    """Ventana expansiva dentro de TR: cada entrenamiento termina antes del bloque que evalúa."""
    bloque = n_tr // (k + 2)
    inicios = [n_tr - (k - i) * bloque for i in range(k)]
    return [(np.arange(0, a), np.arange(a, a + bloque)) for a in inicios]


def tabla_comun(tabla, variables=('ret', 'dist_sma20', 'vol20')):
    """Recorta el inicio para que todas las versiones se evalúen exactamente en las mismas fechas."""
    validas = tabla[list(variables)].notna().all(axis=1)
    return tabla[validas.idxmax():].reset_index(drop=True)


def preparar(tabla, variables, lookback=20):
    """Ventanas, partición por fecha objetivo y escalado ajustado solo con TR."""
    v = features.make_windows(tabla, variables, lookback)
    p = data.split_indices(len(v.y))
    fechas = {k: [v.objetivo[i] for i in idx] for k, idx in p.items()}
    verificar_particion(fechas)
    escalador = features.Scaler.fit(v.X[p['TR']])
    y_media, y_desv = float(v.y[p['TR']].mean()), float(v.y[p['TR']].std())
    salida = dict(variables=variables, lookback=lookback, escalador=escalador, y_media=y_media, y_desv=y_desv, indices=p, ventanas=v)
    for k, idx in p.items():
        salida[f'X_{k}'] = escalador.transform(v.X[idx])
        salida[f'Xcrudo_{k}'] = v.X[idx]
        salida[f'y_{k}'] = v.y[idx]
        salida[f'emision_{k}'] = [v.emision[i] for i in idx]
        salida[f'objetivo_{k}'] = fechas[k]
    return salida


def tabla_particion(d):
    return pd.DataFrame([dict(conjunto=k, ejemplos=len(d[f'y_{k}']), primera_emision=d[f'emision_{k}'][0], ultima_emision=d[f'emision_{k}'][-1],
                              primer_objetivo=d[f'objetivo_{k}'][0], ultimo_objetivo=d[f'objetivo_{k}'][-1]) for k in ('TR', 'VA', 'TE')])


def fila_de_control(d, conjunto='VA', i=0):
    """Una fila completa para explicar por qué el modelo no conoce la respuesta al predecir."""
    indice = d['indices'][conjunto][i]
    v = d['ventanas']
    return dict(entrada_desde=v.inicio[indice], entrada_hasta=v.emision[indice], emision=v.emision[indice], objetivo=v.objetivo[indice],
                rendimiento_objetivo=float(v.y[indice]))


# Modelos clásicos
def ajustar_lineal(X, y, alpha=0.0):
    """Mínimos cuadrados con intercepto. alpha > 0 es Ridge (L2); el intercepto no se penaliza."""
    media_x, media_y = X.mean(axis=0), y.mean()
    Xc = X - media_x
    w = np.linalg.solve(Xc.T @ Xc + (alpha + 1e-9) * np.eye(X.shape[1]), Xc.T @ (y - media_y))
    return w, float(media_y - media_x @ w)


def plano(X):
    return X.reshape(len(X), -1)


def prediccion_lineal(d, conjunto, w, b):
    return plano(d[f'X_{conjunto}']) @ w + b


def ajustar_lineal_modelo(d, alpha=0.0):
    w, b = ajustar_lineal(plano(d['X_TR']), d['y_TR'], alpha)
    return dict(tipo='lineal', w=w, b=b, alpha=alpha)


# Redes (Keras). Se importa aquí para que el agente no dependa de esta librería.
def crear_mlp(entradas, hu, lr, hl=2, dropout=0.0, l2=0.0):
    import keras
    from keras import layers, regularizers
    r = regularizers.L2(l2) if l2 else None
    red = keras.Sequential([layers.Input((entradas,))])
    for _ in range(hl):
        red.add(layers.Dense(hu, activation='relu', kernel_regularizer=r))
        if dropout:
            red.add(layers.Dropout(dropout))
    red.add(layers.Dense(1, activation='linear'))
    red.compile(loss='mse', optimizer=keras.optimizers.Adam(lr))
    return red


def crear_lstm(pasos, variables, hu, lr, dropout=0.0):
    import keras
    from keras import layers
    red = keras.Sequential([layers.Input((pasos, variables)), layers.LSTM(hu)])
    if dropout:
        red.add(layers.Dropout(dropout))
    red.add(layers.Dense(1, activation='linear'))
    red.compile(loss='mse', optimizer=keras.optimizers.Adam(lr))
    return red


def entrenar(red, Xtr, ytr, Xva, yva, semilla, epocas=200, lote=64, paciencia=15):
    """Parada temprana con VA restaurando los mejores pesos. Detiene el proceso si la pérdida no es finita."""
    import keras
    keras.utils.set_random_seed(semilla)
    inicio = time.perf_counter()
    h = red.fit(Xtr, ytr, validation_data=(Xva, yva), epochs=epocas, batch_size=lote, shuffle=True, verbose=0,
                callbacks=[keras.callbacks.EarlyStopping(monitor='val_loss', patience=paciencia, restore_best_weights=True),
                           keras.callbacks.TerminateOnNaN()])
    curvas = {k: [float(x) for x in v] for k, v in h.history.items()}
    if not np.isfinite(curvas['loss']).all():
        raise ValueError('Pérdida no finita durante el entrenamiento: revisa escalas, datos e hiperparámetros.')
    return dict(red=red, curvas=curvas, segundos=time.perf_counter() - inicio, mejor_epoca=int(np.argmin(curvas['val_loss'])) + 1,
                parametros=int(red.count_params()))


def construir_red(tipo, d, cfg):
    k = d['X_TR'].shape[2]
    if tipo == 'mlp':
        return crear_mlp(d['X_TR'].shape[1] * k, cfg['hu'], cfg['lr'], dropout=cfg.get('dropout', 0.0), l2=cfg.get('l2', 0.0), hl=cfg.get('hl', 2))
    return crear_lstm(d['X_TR'].shape[1], k, cfg['hu'], cfg['lr'], dropout=cfg.get('dropout', 0.0))


def entradas_red(tipo, X):
    return plano(X) if tipo == 'mlp' else X


def entrenar_red(tipo, d, cfg, semilla, **kw):
    import keras
    keras.utils.set_random_seed(semilla)
    red = construir_red(tipo, d, cfg)
    ytr = (d['y_TR'] - d['y_media']) / d['y_desv']
    yva = (d['y_VA'] - d['y_media']) / d['y_desv']
    return entrenar(red, entradas_red(tipo, d['X_TR']), ytr, entradas_red(tipo, d['X_VA']), yva, semilla, **kw)


def predecir_red(tipo, r, d, conjunto):
    salida = r['red'].predict(entradas_red(tipo, d[f'X_{conjunto}']), verbose=0).ravel()
    return d['y_media'] + d['y_desv'] * salida


# Experimentos
def registrar(experimentos, d, capitulo, variables, modelo, cfg, semilla, tr, va, segundos=0.0, dispositivo='cpu'):
    experimentos.append(dict(capitulo=capitulo, variables=variables, modelo=modelo, configuracion=json.dumps(cfg, ensure_ascii=False), semilla=semilla,
                             dispositivo=dispositivo, segundos=round(segundos, 2), **{f'{k}_TR': v for k, v in metricas(d['y_TR'], tr).items()},
                             **{f'{k}_VA': v for k, v in metricas(d['y_VA'], va).items()}))


def probar_referencias(d, variables, experimentos, dispositivo='cpu'):
    """Referencias: pronóstico cero, regresión lineal y Ridge con los mismos rezagos."""
    registrar(experimentos, d, 7, variables, 'cero', {}, None, np.zeros_like(d['y_TR']), np.zeros_like(d['y_VA']), dispositivo=dispositivo)
    candidatos = []
    for alpha in (0.0, 100.0, 1000.0):
        ajuste = ajustar_lineal_modelo(d, alpha)
        tr, va = prediccion_lineal(d, 'TR', ajuste['w'], ajuste['b']), prediccion_lineal(d, 'VA', ajuste['w'], ajuste['b'])
        registrar(experimentos, d, 7, variables, 'lineal' if not alpha else 'ridge', dict(alpha=alpha), None, tr, va, dispositivo=dispositivo)
        candidatos.append(dict(nombre=f'Lineal alpha={alpha:g}', tipo='lineal', ajuste=ajuste, pred_va=va, variables=variables))
    return candidatos


def probar_red(d, variables, tipo, configs, experimentos, curvas, dispositivo='cpu', semillas=SEMILLAS, **kw):
    """Redes: tres configuraciones elegidas por RMSE de VA; la mejor se repite con tres semillas."""
    mejor = None
    for cfg in configs:
        inicio = time.perf_counter()
        r = entrenar_red(tipo, d, cfg, semillas[0], **kw)
        tr, va = predecir_red(tipo, r, d, 'TR'), predecir_red(tipo, r, d, 'VA')
        registrar(experimentos, d, 8, variables, tipo, {**cfg, 'parametros': r['parametros'], 'mejor_epoca': r['mejor_epoca']}, semillas[0], tr, va, time.perf_counter() - inicio, dispositivo)
        rmse = metricas(d['y_VA'], va)['RMSE']
        if mejor is None or rmse < mejor[0]:
            mejor = (rmse, cfg)
    corridas = []
    for s in semillas:
        inicio = time.perf_counter()
        r = entrenar_red(tipo, d, mejor[1], s, **kw)
        tr, va = predecir_red(tipo, r, d, 'TR'), predecir_red(tipo, r, d, 'VA')
        registrar(experimentos, d, 8, variables, f'{tipo}_mejor', {**mejor[1], 'parametros': r['parametros'], 'mejor_epoca': r['mejor_epoca']}, s, tr, va, time.perf_counter() - inicio, dispositivo)
        corridas.append((r, va))
    rmses = [metricas(d['y_VA'], va)['RMSE'] for _, va in corridas]
    curvas[f'{variables}/{tipo}'] = corridas[0][0]['curvas']
    return dict(nombre=f'{tipo.upper()} ensamble de {len(semillas)} semillas, {mejor[1]["hu"]} neuronas', tipo=tipo, cfg=mejor[1], variables=variables, resultados=[r for r, _ in corridas],
                pred_va=np.mean([va for _, va in corridas], axis=0), rmse_media=float(np.mean(rmses)), rmse_desv=float(np.std(rmses)))


def validacion_expansiva(d, redes=(), **kw):
    """Validación temporal: tres ventanas dentro de TR. Las transformaciones se reajustan solo con cada entrenamiento."""
    v, indices, filas = d['ventanas'], d['indices']['TR'], []
    for n, (a, b) in enumerate(folds_expansivos(len(indices)), 1):
        X_ent, y_ent, X_blo, y_blo = v.X[indices[a]], v.y[indices[a]], v.X[indices[b]], v.y[indices[b]]
        escalador = features.Scaler.fit(X_ent)
        Xe, Xb = escalador.transform(X_ent), escalador.transform(X_blo)
        base = dict(ventana=n, entrenamiento_hasta=v.objetivo[indices[a][-1]], bloque_desde=v.objetivo[indices[b][0]], bloque_hasta=v.objetivo[indices[b][-1]],
                    ejemplos_entrenamiento=len(a), ejemplos_bloque=len(b))
        filas.append({**base, 'modelo': 'cero', **metricas(y_blo, np.zeros_like(y_blo))})
        w, c = ajustar_lineal(plano(Xe), y_ent)
        filas.append({**base, 'modelo': 'lineal', **metricas(y_blo, plano(Xb) @ w + c)})
        for tipo, cfg in redes:
            corte = int(len(Xe) * 0.85)  # la parada temprana usa el tramo final del propio entrenamiento
            y_media, y_desv = float(y_ent.mean()), float(y_ent.std())
            sub = dict(X_TR=Xe[:corte], y_TR=y_ent[:corte], X_VA=Xe[corte:], y_VA=y_ent[corte:], y_media=y_media, y_desv=y_desv)
            r = entrenar_red(tipo, sub, cfg, SEMILLAS[0], **kw)
            pred = y_media + y_desv * r['red'].predict(entradas_red(tipo, Xb), verbose=0).ravel()
            filas.append({**base, 'modelo': tipo, **metricas(y_blo, pred)})
    return filas


# Reglas de señal
def velas_de(tabla, fechas):
    indice = tabla.set_index('date')
    return indice.loc[fechas].reset_index()


def senales(pronostico, velas, umbral, filtro):
    pasa = np.asarray(pronostico) > umbral
    if filtro == 'sma20':
        pasa = pasa & (velas.close.to_numpy() > velas.sma20.to_numpy())
    return pasa


def probar_reglas(pronostico, velas, comision, capital=100_000.0):
    """Hasta cinco umbrales, con y sin filtro técnico. El filtro cambia operaciones, no las predicciones."""
    salida = []
    for filtro in FILTROS:
        for umbral in UMBRALES:
            r = simular(velas, senales(pronostico, velas, umbral, filtro), comision, capital)
            salida.append(dict(umbral=umbral, filtro=filtro, rendimiento=r['rendimiento'], drawdown=r['drawdown'], operaciones=r['operaciones'],
                               win_rate=r['win_rate'], costos=r['costos']))
    return salida


# Sesgo y varianza
def descomposicion(y, predicciones):
    """Sobre reentrenamientos: MSE = (sesgo² + ruido) + varianza. Con datos reales g(x) es desconocida,

    así que sesgo² y ruido solo se reportan juntos. La varianza sí se mide de verdad entre reentrenamientos.
    No confundir con MAE ni con la dispersión de una sola predicción.
    """
    y = np.asarray(y, dtype=float).reshape(-1)
    p = np.asarray(predicciones, dtype=float)
    if p.ndim != 2 or p.shape[1] != len(y):
        raise ValueError(f'Forma recibida {p.shape}; esperada (reentrenamientos, {len(y)}).')
    mse = float(((p - y) ** 2).mean())
    varianza = float(p.var(axis=0).mean())
    return dict(mse=mse, varianza=varianza, sesgo2_mas_ruido=mse - varianza, mse_promedio=float(((p.mean(axis=0) - y) ** 2).mean()), reentrenamientos=len(p))


def bootstrap_bloques(n, rng, largo=20):
    """Remuestreo por bloques para respetar la dependencia temporal al medir varianza."""
    inicios = rng.integers(0, n - largo + 1, size=n // largo + 1)
    return np.concatenate([np.arange(a, a + largo) for a in inicios])[:n]


def diagnostico_clasico(d, ajustar_predecir, reentrenos=12, semilla=7, fraccion=1.0):
    """Reentrena con remuestreos de TR y mide en VA. ajustar_predecir(Xtr, ytr, Xva) -> predicción."""
    rng = np.random.default_rng(semilla)
    Xtr, ytr, Xva = plano(d['X_TR']), d['y_TR'], plano(d['X_VA'])
    inicio = int(len(Xtr) * (1 - fraccion))  # "más datos": menos fracción usa solo el tramo reciente de TR
    Xtr, ytr = Xtr[inicio:], ytr[inicio:]
    pred = []
    for _ in range(reentrenos):
        idx = bootstrap_bloques(len(Xtr), rng)
        pred.append(ajustar_predecir(Xtr[idx], ytr[idx], Xva))
    return descomposicion(d['y_VA'], np.array(pred))


def tacticas_clasicas(d, reentrenos=12):
    """Tácticas de mitigación de la clase, medidas con estos datos. RF y boosting son diagnóstico, no se despliegan."""
    from sklearn.decomposition import PCA
    from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Lasso
    from sklearn.pipeline import make_pipeline

    def lineal(alpha):
        def f(X, y, Xva):
            w, b = ajustar_lineal(X, y, alpha)
            return Xva @ w + b
        return f

    def sk(fabrica):
        def f(X, y, Xva):
            return fabrica().fit(X, y).predict(Xva)
        return f

    casos = [
        ('Base: regresión lineal', 'Referencia', lineal(0.0), {}),
        ('Agregar más datos (referencia con solo 50% de TR)', 'Agregar más datos', lineal(0.0), {'fraccion': 0.5}),
        ('Ridge L2 alpha=100', 'Regularización', lineal(100.0), {}),
        ('Ridge L2 alpha=1000', 'Regularización', lineal(1000.0), {}),
        ('Lasso L1', 'Regularización', sk(lambda: Lasso(alpha=1e-3, max_iter=5000)), {}),
        ('PCA 5 componentes + lineal', 'Selección de características (PCA)', sk(lambda: make_pipeline(PCA(5), Lasso(alpha=1e-9, max_iter=5000))), {}),
        ('Bagging: Random Forest', 'Bagging', sk(lambda: RandomForestRegressor(n_estimators=40, max_depth=4, n_jobs=-1, random_state=0)), {}),
        ('Boosting: gradiente', 'Boosting', sk(lambda: HistGradientBoostingRegressor(max_depth=2, max_iter=60, learning_rate=0.05, random_state=0)), {}),
    ]
    salida = []
    for nombre, estrategia, funcion, kw in casos:
        r = diagnostico_clasico(d, funcion, reentrenos=reentrenos, **kw)
        salida.append(dict(modelo=nombre, estrategia=estrategia, **r))
    return salida


def tacticas_redes(d, semillas=SEMILLAS, **kw):
    """Complejidad, dropout y L2 en redes: la varianza se mide entre semillas."""
    casos = [
        ('MLP pequeña', 'Referencia de red', 'mlp', dict(hu=8, lr=1e-3)),
        ('MLP grande (más capas y neuronas)', 'Aumentar complejidad', 'mlp', dict(hu=64, lr=1e-3, hl=3)),
        ('MLP grande + Dropout 0.3', 'Regularización', 'mlp', dict(hu=64, lr=1e-3, hl=3, dropout=0.3)),
        ('MLP grande + L2', 'Regularización', 'mlp', dict(hu=64, lr=1e-3, hl=3, l2=1e-3)),
        ('LSTM', 'Red recurrente', 'lstm', dict(hu=16, lr=1e-3)),
    ]
    salida = []
    for nombre, estrategia, tipo, cfg in casos:
        pred = [predecir_red(tipo, entrenar_red(tipo, d, cfg, s, **kw), d, 'VA') for s in semillas]
        salida.append(dict(modelo=nombre, estrategia=estrategia, **descomposicion(d['y_VA'], np.array(pred))))
    return salida


# Entorno del agente futuro (capítulo 10)
def transicion_ejemplo(efectivo, precio_ejecucion, cierre, comision):
    """Una transición calculada a mano: comprar con todo el efectivo y valorar al cierre. La recompensa es el cambio del patrimonio."""
    nocional = efectivo / (1 + comision)
    cantidad = nocional / precio_ejecucion
    costo = nocional * comision
    nuevo = cantidad * cierre
    return dict(cantidad=cantidad, costo=costo, patrimonio_nuevo=nuevo, recompensa=nuevo - efectivo)


def huella(configuracion):
    return hashlib.sha256(json.dumps(configuracion, sort_keys=True, default=str).encode()).hexdigest()


# Sello de apertura de TE
def abrir_te(ruta, huella):
    """TE se evalúa una sola vez con la configuración congelada. Cualquier cambio posterior queda declarado."""
    ruta = Path(ruta)
    sello = json.loads(ruta.read_text(encoding='utf-8')) if ruta.exists() else dict(huella=huella, aperturas=0, contaminado=False)
    sello['aperturas'] += 1
    if huella != sello['huella']:
        sello['contaminado'] = True
    ruta.write_text(json.dumps(sello, indent=2), encoding='utf-8')
    return sello


# Empaquetado del modelo aprobado
def contrato_lineal(d, ajuste):
    """Una regresión lineal se expresa como una capa densa sobre las variables ya escaladas y en y normalizada."""
    w = np.asarray(ajuste['w']).reshape(-1, 1) / d['y_desv']
    b = np.array([(ajuste['b'] - d['y_media']) / d['y_desv']])
    return [[{'tipo': 'dense', 'activacion': 'linear'}]], {'m0_c0_w': w, 'm0_c0_b': b}


def contrato_redes(resultados):
    """Un ensamble promedia varias semillas: bagging de redes para reducir la varianza."""
    miembros, pesos = [], {}
    for i, r in enumerate(resultados):
        m, p = model.exportar_keras(r['red'], i)
        miembros.append(m)
        pesos |= p
    return miembros, pesos


def guardar_modelo(carpeta, version, tipo, d, umbral, filtro, miembros, pesos, extra=None):
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    contrato = dict(version=version, tipo=tipo, lookback=d['lookback'], variables=d['variables'], umbral=umbral, filtro=filtro,
                    escalador=d['escalador'].to_dict(), y_media=d['y_media'], y_desv=d['y_desv'], miembros=miembros, **(extra or {}))
    (carpeta / 'contrato.json').write_text(json.dumps(contrato, indent=2, ensure_ascii=False), encoding='utf-8')
    if pesos:
        np.savez(carpeta / 'modelo.npz', **pesos)
    return model.cargar(carpeta)
