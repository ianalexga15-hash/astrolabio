# Orden que espera en el libro (sin comisión)

Pedido de Alex el 2026-11-06: «intenta usar sin comisión». MEXC informó para su cuenta, por API, 0 % para la orden que espera en el libro (maker) en los 40 pares y entre 0 % y 0.08 % para la que compra o vende al instante (taker). Este diseño aplica a la simulación Paper; la ejecución real (etapa 4) necesita otra decisión de Alex.

## Qué hace

**Compra.** Cuando una compra armada cumple todas sus condiciones, el bot no compra al instante: deja una orden al mejor precio de compra de ese segundo.
- **Se llena** solo si después el precio de venta baja hasta ese límite. Compra a ese precio, sin comisión y sin deslizamiento. Es una regla conservadora: no conocemos el lugar en la fila del libro, así que no basta con tocar el precio.
- **Se cancela** si deja de cumplirse una condición, por ejemplo si el precio se aleja y ya no se persigue. Vuelve a ponerse al mejor precio de ese momento cuando todo se cumple otra vez.
- **Plazo:** si en `espera_max_min` minutos desde la primera vez no se llenó y las condiciones siguen cumpliéndose, compra al instante como antes, con la comisión real del par. Así no se pierde la subida.
- **Riesgo:** puede cancelar en cualquier segundo; con el riesgo en contra la orden no se llena.

**Venta en el objetivo.** La venta queda esperando en el libro al precio objetivo. Cuando el precio de compra llega ahí, vende a ese precio y sin comisión.

**Stop de pérdida, stop móvil y cierre manual.** Siguen siendo inmediatos, con la comisión real del par: la protección no espera.

## Parámetros, en Sistema

- **Espera en el libro** (`espera_max_min`): 30 minutos en la configuración actual. Con 0 todo vuelve a ser al instante.
- **Comisión de la orden que espera** (`comision_espera`): 0, como informó MEXC el 2026-11-06.

## Cómo se ve

- **Radar:** muestra «en espera a» y el precio límite.
- **Operaciones:** la compra o venta llenada en espera aparece con el supuesto «orden en espera al precio límite» o «al precio objetivo», con su comisión.
- **Reinicio:** la orden en espera queda guardada con la compra armada.

## Límites declarados

- La simulación solo ve el mejor precio de compra y de venta una vez por segundo, no las operaciones del mercado: puede perder llenados reales.
- Una orden que espera se llena sobre todo cuando el precio baja, es decir, en contra. Hay que medir en Paper si el ahorro de 0.05 % compensa esas compras y las que se pierden.
