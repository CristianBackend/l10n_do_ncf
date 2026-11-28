# Pendientes

Cosas vistas y dejadas a propósito para más adelante, con lo que haría falta
saber para hacerlas bien. No son fallos abiertos: lo que hay funciona y está
probado; lo que se discute aquí es si debería hacer otra cosa.

## 1. El generador debería consumir primero la secuencia más antigua

**Qué hace hoy.** Cuando hay **varias secuencias activas del mismo tipo**, el
generador usa la de **id más alto** con números libres, es decir la última
registrada:

- `models/account_move.py`, `_generate_ncf()`: la búsqueda de candidatas y el
  `SELECT ... FOR UPDATE NOWAIT` van los dos con `id desc`;
- `models/registro_unico.py`, `_generate_b12_ncf()`: igual, para que el B12 se
  comporte como las facturas.

El punto de venta no entra aquí: cada caja nombra su secuencia en la
configuración (`l10n_do_ncf_sequence_id` y las de cada tipo de cliente), así
que no hay nada que elegir.

**Qué tiene de malo.** Si el contador registra y activa un rango nuevo **antes**
de agotar el que está usando, los números que quedaban en el viejo **se quedan
sin usar**: el generador salta al rango nuevo y nunca vuelve al anterior. No se
emite nada inválido ni se repite ningún NCF, pero se desperdician números
autorizados por la DGII, y el panel los seguirá contando como disponibles.

Está fijado tal cual en
`tests/test_ncf_alerts.py::TestNcfAlerts::test_the_next_active_sequence_is_used_on_its_own`,
que hoy describe el comportamiento actual: con una secuencia 1-2 y otra
101-200, la factura sale con `B0100000101`.

**Qué haría falta para cambiarlo.** Pasar las dos búsquedas a `id asc` es una
línea en cada sitio, pero antes hay que decidir una regla, porque "la más
antigua" no es lo único que cuenta:

- entre dos rangos con números libres, puede interesar más gastar el que
  **vence antes** (los NCF en papel caducan: `expiration_date`), y eso no
  siempre es el de id más bajo;
- hay que confirmar con el contador que la DGII no espera un orden concreto al
  reportar en el 607 un mes con dos rangos en uso.

Es decir: la decisión es fiscal, no técnica. Cuando esté tomada, el cambio es
el orden de esas dos búsquedas y actualizar la prueba de arriba para que
describa la regla nueva.
