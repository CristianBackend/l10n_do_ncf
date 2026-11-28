# Diferencias de uso en Odoo 16 (para la capacitación)

Qué hace distinto el contador en Odoo 16 respecto a lo que ya conoce de la
versión 19. Todo lo demás (NCF, 606/607/608/609, e-CF, POS) se usa igual.

Este documento se va completando a medida que avanza el porte; cada punto dice
por qué la diferencia existe, para poder explicarla.

## 1. Compras a proveedor extranjero: hay que quitar el ITBIS de la línea

**Qué pasa.** Al poner un producto de servicio en la línea de una factura de
compra, Odoo 16 le pone el **impuesto de compra por defecto de la compañía**, y
al cargar el plan contable dominicano ese impuesto es un ITBIS. La versión 19 ya
no hace eso: la línea nace sin impuestos.

**Qué hay que hacer.** Quitar ese ITBIS de la línea. Un pago al exterior
(B17 / e-CF E47) **no lleva ITBIS** (instructivo del 606: el B17 no llena las
casillas de ITBIS), así que mientras el ITBIS esté puesto la compra se queda
como "Con comprobante del proveedor". En cuanto se quita:

- el "Tipo de compra" pasa solo a **Pago al exterior**, y
- se agrega sola la **retención de ISR del 27 %** en esa línea (la que esté
  indicada en la compañía, pestaña "Retenciones del pago al exterior").

**Con varias líneas** la retención se agrega en todas, también en las que se
añaden después de que la factura ya sea un pago al exterior.

**Si una línea queda sin retención** (porque se le quitó a mano), la factura
**no se confirma**: avisa "Pago al exterior: falta la retención de ISR en ..." y
nombra la línea. Es a propósito: una línea sin retención hace que la factura
declare menos ISR del que toca. Para que una línea vaya sin retención —por
ejemplo viáticos de un viaje— se marca su producto con **"Sin retención en
pagos al exterior"** (pestaña Contabilidad del producto), que es la forma
prevista; entonces ni se sugiere ni se exige.

> Atajo útil: si se prefiere no quitar el ITBIS línea por línea, se puede dejar
> la compañía **sin impuesto de compra por defecto** (Ajustes de contabilidad).
> Entonces las líneas nacen sin impuestos, igual que en la 19, y el contador
> pone el ITBIS solo donde haga falta.

## 2. El tipo de retención de ISR (casilla 17 del 606) lo confirma el contador

**Qué pasa.** En la 19, la configuración automática ponía el tipo de retención
del 606 en dos impuestos del plan, porque sus plantillas lo decían sin
ambigüedad: honorarios a personas físicas (tipo **02**) y alquileres (tipo
**01**), ambas al 15 %. El plan contable de Odoo 16 **no trae esas plantillas**:
las suyas son "Retención 10% ISR Honorarios a Físicas" y "Retención 10% ISR
Alquileres a Físicas", con otra tasa. El módulo no inventa el tipo a partir de
una tasa distinta.

**Qué hay que hacer.** La tarjeta **"Configuración pendiente"** del Panel e-CF
lista las retenciones de ISR de compras que no tienen tipo (grupo "Retenciones
de ISR sin tipo (606, casilla 17)"). El contador abre cada impuesto y elige el
tipo. Mientras falte, el 606 marca esas compras como pendientes.

Las tasas del plan de 16 también son distintas: ver `docs/retenciones_tabla.md`,
que es la tabla para revisar con el contador.

## 3. Anticipos de venta: el producto "Anticipo" necesita ITBIS

**Qué pasa.** La línea de un anticipo lleva los impuestos del **producto
"Anticipo"**, no los del pedido. Odoo 16 le pone a ese producto los impuestos
que se indiquen en el asistente "Factura de anticipo" ("Impuestos usados para
los depósitos") la primera vez que lo crea; después ya no vuelve a tocarlo. La
versión 19 copia los impuestos del pedido en cada anticipo.

**Qué hay que hacer.** Dejar el producto "Anticipo" con el **ITBIS 18 %** (o el
que corresponda) una sola vez. Si se queda sin impuesto, el e-CF **no deja
confirmar** la factura del anticipo y avisa: *"La línea «Down payment of ...» no
tiene ITBIS. Asígnele ITBIS 18 %, 16 %, 0 % o Exento: sin impuesto, la
plataforma le aplicaría el 18 %"*. El aviso es correcto: la DGII calcularía el
ITBIS por su cuenta.

**Y el importe fijo del anticipo es la base, no el total.** En Odoo 16, si en el
asistente se pide un anticipo fijo de RD$20,000, la factura sale por
**RD$23,600** (20,000 + 18 % de ITBIS): el importe va al precio de la línea. La
versión 19 lo trata como el total con el ITBIS ya incluido. Para cobrar
exactamente RD$20,000 hay que pedir RD$16,949.15, o usar el anticipo por
porcentaje.

Lo demás de los anticipos con e-CF no cambia: la factura final va por el total
del pedido y cada anticipo se anula con una E34.

## 4. Punto de venta con e-CF: el aviso de "emitiendo" no lleva texto

**Qué pasa.** Al cobrar en una caja con e-CF, la pantalla se bloquea mientras
la plataforma emite el comprobante (lo normal son 0.6–1.1 s). En la versión 19
ese bloqueo muestra el texto *"Emitiendo comprobante electrónico…"*; en Odoo 16
el bloqueo de pantalla del sistema **no admite mensaje** (`ui.block()` no
recibe parámetros), así que se ve el indicador de espera sin texto.

**Qué hay que hacer.** Nada: es solo el aviso. Todo lo demás del cobro es
igual, incluido lo importante: si la plataforma no responde, **la venta no se
cierra** y aparecen las tres opciones de siempre —Reintentar (misma clave, no
gasta otro e-NCF), Emitir en papel o Volver—, y si la DGII la rechaza se
muestra el motivo.

## 5. Diarios de tarjeta de crédito: la forma de pago 03 se pone a mano

**Qué pasa.** La "Forma de pago DGII" del 606/607 se deduce del tipo de diario:
efectivo → 01, banco → 02, tarjeta → 03. Odoo 16 **no tiene el tipo de diario
"Tarjeta de crédito"** (llegó después): un diario de tarjeta se crea como tipo
Banco, así que queda en **02 - Cheques / transferencias / depósito**.

**Qué hay que hacer.** En el diario de la tarjeta, poner a mano la forma de pago
**03 - Tarjeta de crédito / débito**. Lo demás (efectivo y banco) se configura
solo.
