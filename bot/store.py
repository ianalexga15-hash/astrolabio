"""Persistencia en SQLite. Cada ciclo se guarda en una sola transacción: o queda completo o no queda nada."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone

from bot.paper import Cuenta

ESQUEMA = '''
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, tipo TEXT NOT NULL, etiqueta TEXT, parametros TEXT, creado TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS velas(simbolo TEXT, open_time INTEGER, open REAL, high REAL, low REAL, close REAL, volume REAL,
    close_time INTEGER, PRIMARY KEY(simbolo, open_time));
CREATE TABLE IF NOT EXISTS procesadas(run TEXT, simbolo TEXT, vela INTEGER, estado TEXT NOT NULL, creado TEXT NOT NULL,
    PRIMARY KEY(run, simbolo, vela));
CREATE TABLE IF NOT EXISTS decisiones(id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL, vela INTEGER NOT NULL,
    fecha_vela TEXT NOT NULL, creado TEXT NOT NULL, modelo_version TEXT, pronostico REAL, senal INTEGER, umbral REAL, filtro TEXT,
    accion_propuesta TEXT, justificacion TEXT, origen TEXT, llm_modelo TEXT, latencia_ms REAL, herramientas TEXT,
    aprobada INTEGER, accion_final TEXT, motivos TEXT, precio REAL, indicadores TEXT);
CREATE TABLE IF NOT EXISTS ordenes(id INTEGER PRIMARY KEY AUTOINCREMENT, run TEXT NOT NULL, decision_id INTEGER, vela INTEGER,
    creado TEXT NOT NULL, lado TEXT, cantidad REAL, precio REAL, comision REAL, estado TEXT NOT NULL, motivo TEXT, resultado REAL, modelo_costos TEXT);
CREATE TABLE IF NOT EXISTS cuentas(run TEXT PRIMARY KEY, datos TEXT NOT NULL, patrimonio_maximo REAL);
CREATE TABLE IF NOT EXISTS patrimonio(run TEXT, vela INTEGER, fecha TEXT, efectivo REAL, cantidad REAL, precio REAL,
    patrimonio REAL, PRIMARY KEY(run, vela));
CREATE TABLE IF NOT EXISTS errores(id INTEGER PRIMARY KEY AUTOINCREMENT, creado TEXT NOT NULL, etapa TEXT, error TEXT,
    causa TEXT, accion TEXT, resultado TEXT);
CREATE TABLE IF NOT EXISTS estado(run TEXT PRIMARY KEY, estado TEXT NOT NULL, motivo TEXT, por_fallo INTEGER DEFAULT 0,
    proximo_reintento REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS configuracion(id INTEGER PRIMARY KEY AUTOINCREMENT, creado TEXT NOT NULL, datos TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS acceso(id INTEGER PRIMARY KEY CHECK (id = 1), creado TEXT NOT NULL, datos TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sesiones(huella TEXT PRIMARY KEY, vence REAL NOT NULL);
CREATE TABLE IF NOT EXISTS salidas_pendientes(run TEXT PRIMARY KEY, entrada REAL, motivo TEXT, detectado REAL);
'''


def ahora_iso():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Store:
    def __init__(self, ruta):
        self.ruta = str(ruta)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.ruta, check_same_thread=False, isolation_level=None, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(ESQUEMA)
        if 'modelo_costos' not in {f[1] for f in self.db.execute('PRAGMA table_info(ordenes)')}:  # bases creadas antes de esta columna
            self.db.execute('ALTER TABLE ordenes ADD COLUMN modelo_costos TEXT')
        self._en_tx = 0

    @contextmanager
    def transaccion(self):
        with self._lock:
            externa = self._en_tx == 0
            if externa:
                self.db.execute('BEGIN IMMEDIATE')
            self._en_tx += 1
            try:
                yield
            except BaseException:
                self._en_tx -= 1
                if externa:
                    self.db.execute('ROLLBACK')
                raise
            else:
                self._en_tx -= 1
                if externa:
                    self.db.execute('COMMIT')

    def _todas(self, sql, *args):
        with self._lock:
            return [dict(f) for f in self.db.execute(sql, args).fetchall()]

    def _una(self, sql, *args):
        with self._lock:
            f = self.db.execute(sql, args).fetchone()
        return dict(f) if f else None

    def _ejecutar(self, sql, *args):
        with self._lock:
            return self.db.execute(sql, args)

    # Runs
    def abrir_run(self, ident, tipo='live', etiqueta='', parametros=None):
        self._ejecutar('INSERT OR IGNORE INTO runs VALUES(?,?,?,?,?)', ident, tipo, etiqueta, json.dumps(parametros or {}), ahora_iso())

    def run(self, ident):
        return self._una('SELECT * FROM runs WHERE id=?', ident)

    def runs(self):
        return self._todas('SELECT * FROM runs ORDER BY creado')

    # Idempotencia
    def ya_procesada(self, run, simbolo, vela):
        return self._una('SELECT 1 x FROM procesadas WHERE run=? AND simbolo=? AND vela=?', run, simbolo, int(vela)) is not None

    def marcar_procesada(self, run, simbolo, vela, estado):
        self._ejecutar('INSERT INTO procesadas VALUES(?,?,?,?,?)', run, simbolo, int(vela), estado, ahora_iso())

    def procesadas(self, run):
        return self._todas('SELECT * FROM procesadas WHERE run=? ORDER BY vela', run)

    def ultima_procesada(self, run, simbolo):
        f = self._una('SELECT MAX(vela) v FROM procesadas WHERE run=? AND simbolo=?', run, simbolo)
        return f['v'] if f else None

    # Velas
    def guardar_velas(self, simbolo, filas):
        with self.transaccion():
            self.db.executemany('INSERT OR REPLACE INTO velas VALUES(?,?,?,?,?,?,?,?)',
                                [(simbolo, int(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[4]), float(f[5]), int(f[6])) for f in filas])

    def velas(self, simbolo, limite=400):
        filas = self._todas('SELECT * FROM velas WHERE simbolo=? ORDER BY open_time DESC LIMIT ?', simbolo, limite)
        return filas[::-1]

    # Decisiones y órdenes
    def guardar_decision(self, **d):
        columnas = ','.join(d)
        marcas = ','.join('?' * len(d))
        c = self._ejecutar(f'INSERT INTO decisiones({columnas},creado) VALUES({marcas},?)', *d.values(), ahora_iso())
        return c.lastrowid

    def ultima_decision(self, run):
        return self._una('SELECT * FROM decisiones WHERE run=? ORDER BY id DESC LIMIT 1', run)

    def decisiones(self, run, limite=1000):
        return self._todas('SELECT * FROM decisiones WHERE run=? ORDER BY id LIMIT ?', run, limite)

    def guardar_orden(self, run, decision_id, vela, lado, estado, motivo='', cantidad=0.0, precio=0.0, comision=0.0, resultado=None, modelo_costos=None):
        self._ejecutar('INSERT INTO ordenes(run,decision_id,vela,creado,lado,cantidad,precio,comision,estado,motivo,resultado,modelo_costos) '
                       'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', run, decision_id, vela, ahora_iso(), lado, cantidad, precio, comision, estado, motivo, resultado, modelo_costos)

    def ordenes(self, run, limite=2000):
        return self._todas('SELECT * FROM ordenes WHERE run=? ORDER BY id LIMIT ?', run, limite)

    def grupo(self, tabla, prefijo, limite=3000):
        """Filas recientes de todas las corridas de un grupo, por ejemplo live:BTCUSDT, live:ETHUSDT..."""
        if tabla not in ('decisiones', 'ordenes'):
            raise ValueError(f'Tabla no permitida: {tabla}.')
        filas = self._todas(f'SELECT * FROM {tabla} WHERE run LIKE ? ORDER BY id DESC LIMIT ?', f'{prefijo}:%', limite)
        return filas[::-1]

    def compras_autorizadas(self, prefijo, fecha_vela):
        """Compras aprobadas por todas las corridas del grupo en una vela diaria: lo que cuenta el tope diario de la cartera."""
        return self._una("SELECT COUNT(*) n FROM decisiones WHERE run LIKE ? AND fecha_vela=? AND accion_final='comprar'", f'{prefijo}:%', fecha_vela)['n']

    def runs_de(self, prefijo):
        return self._todas('SELECT * FROM runs WHERE id LIKE ? ORDER BY id', f'{prefijo}:%')

    # Cuenta y patrimonio
    def guardar_cuenta(self, run, cuenta, maximo=None):
        previo = self._una('SELECT patrimonio_maximo m FROM cuentas WHERE run=?', run)
        pico = max(filter(None, [maximo, previo and previo['m']]), default=None)
        self._ejecutar('INSERT OR REPLACE INTO cuentas VALUES(?,?,?)', run, json.dumps(asdict(cuenta)), pico)

    def cargar_cuenta(self, run):
        f = self._una('SELECT datos FROM cuentas WHERE run=?', run)
        return Cuenta(**json.loads(f['datos'])) if f else None

    def patrimonio_maximo(self, run):
        f = self._una('SELECT patrimonio_maximo m FROM cuentas WHERE run=?', run)
        return f['m'] if f else None

    def fijar_patrimonio_maximo(self, run, valor):
        self._ejecutar('UPDATE cuentas SET patrimonio_maximo=? WHERE run=?', valor, run)

    def marcar_patrimonio(self, run, vela, fecha, cuenta, precio):
        self._ejecutar('INSERT OR REPLACE INTO patrimonio VALUES(?,?,?,?,?,?,?)', run, int(vela), fecha, cuenta.efectivo, cuenta.cantidad, precio,
                       cuenta.efectivo + cuenta.cantidad * precio)

    def ultimo_patrimonio(self, run):
        f = self._una('SELECT patrimonio FROM patrimonio WHERE run=? ORDER BY vela DESC LIMIT 1', run)
        return f['patrimonio'] if f else None

    def borrar_patrimonio(self, run):
        self._ejecutar('DELETE FROM patrimonio WHERE run=?', run)

    def patrimonio(self, run, limite=5000):
        return self._todas('SELECT * FROM patrimonio WHERE run=? ORDER BY vela LIMIT ?', run, limite)

    def ultimo_stop_con_perdida(self, run):
        """Apertura (ms) de la vela diaria en que el último stop cerró perdiendo; None si no hubo."""
        f = self._una("SELECT vela, creado FROM ordenes WHERE run=? AND estado='ejecutada' AND motivo='stop' AND resultado < 0 "
                      'ORDER BY id DESC LIMIT 1', run)
        if f is None:
            return None
        ms = f['vela'] if f['vela'] is not None else datetime.fromisoformat(f['creado']).timestamp() * 1000  # el reflejo no anota vela
        return ms // 86_400_000 * 86_400_000

    # Bitácora de errores
    def registrar_error(self, etapa, error, causa='', accion='', resultado=''):
        self._ejecutar('INSERT INTO errores(creado,etapa,error,causa,accion,resultado) VALUES(?,?,?,?,?,?)', ahora_iso(), etapa, error, causa, accion, resultado)

    def errores(self, limite=500):
        return self._todas('SELECT * FROM errores ORDER BY id DESC LIMIT ?', limite)[::-1]

    # Estado del bot
    def guardar_estado(self, run, estado, motivo='', por_fallo=False, proximo_reintento=0.0):
        self._ejecutar('INSERT OR REPLACE INTO estado VALUES(?,?,?,?,?)', run, estado, motivo, int(por_fallo), proximo_reintento)

    def cargar_estado(self, run):
        return self._una('SELECT * FROM estado WHERE run=?', run)

    # Configuración (solo la cambia una persona autenticada)
    def guardar_configuracion(self, datos):
        self._ejecutar('INSERT INTO configuracion(creado,datos) VALUES(?,?)', ahora_iso(), json.dumps(datos))

    def guardar_acceso(self, datos):
        """Solo la huella de la contraseña personal: nunca la contraseña."""
        self._ejecutar('INSERT OR REPLACE INTO acceso(id,creado,datos) VALUES(1,?,?)', ahora_iso(), json.dumps(datos))

    def cargar_acceso(self):
        f = self._una('SELECT creado, datos FROM acceso WHERE id=1')
        return json.loads(f['datos']) | dict(creado=f['creado']) if f else None

    def guardar_sesiones(self, sesiones):
        """Copia las sesiones abiertas del panel: solo la huella SHA-256 de cada token y cuándo vence, nunca el token."""
        with self.transaccion():
            self.db.execute('DELETE FROM sesiones')
            self.db.executemany('INSERT INTO sesiones(huella,vence) VALUES(?,?)', sesiones.items())

    def sesiones_vigentes(self, ahora):
        """Borra las vencidas y devuelve las demás, de la más antigua a la más nueva."""
        self._ejecutar('DELETE FROM sesiones WHERE vence <= ?', ahora)
        return {f['huella']: f['vence'] for f in self._todas('SELECT huella, vence FROM sesiones ORDER BY vence')}

    def cargar_configuracion(self):
        f = self._una('SELECT datos FROM configuracion ORDER BY id DESC LIMIT 1')
        return json.loads(f['datos']) if f else None
