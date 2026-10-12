# Conector Odoo 19 ↔ ecf-api: diseño (solo lectura, no modifiqué ningún archivo)

**Conclusión:** el conector es viable, pero la API pública de ecf-api hoy no acepta varios datos que Odoo necesita enviar (fecha de emisión, tipo de ingreso, retenciones, descuentos globales, varias formas de pago). Hay que ampliar el DTO de ecf-api y arreglar tres cosas de `l10n_do_ncf` antes de construir encima. Los webhooks ya están firmados.

## 1. Contrato de la API

**Base y autenticación**
- Prefijo `/api/v1`; credencial en `X-API-Key` o `Authorization: Bearer`.
- Respuesta correcta: `{success:true, data}`. Error: `{success:false, error:{code, type, message, details?, timestamp, path}}`; `message` puede ser texto o lista.
- Un campo que no esté en el DTO devuelve 400 (`forbidNonWhitelisted`).
- Otros códigos: 401, 402 (plan o cuota), 403 (scope, u override en PROD), 404, 429 (60 peticiones/min por IP).
- El ambiente lo decide `company.dgiiEnv`; que la clave sea `test` o `live` no influye.

**`POST /invoices`** (scope `INVOICES_WRITE`) responde 202 con la factura en `QUEUED`: `id`, `encf`, totales, `hasSignedXml`, `isRfce`, líneas.

| Bloque | Campos aceptados |
|---|---|
| Raíz | `companyId` (UUID), `ecfType`, `buyer`, `items` (1–10 000), `payment`, `reference`, `currency`, `transport`, `additionalInfo`, `foreignBeneficiary`, `retentionAmount`, `idempotencyKey` (≤64), `metadata`, `encfOverride` y `emitterOverride` (403 en PROD) |
| `buyer` | `rnc` (9 u 11 dígitos), `name` (2–250), `contactName`, `email`, `phone`, `address`, `municipality` y `province` (código DGII de 6 dígitos), `type`, datos de entrega y orden de compra |
| `items[]` | `description` (≤500), `quantity` (≥0.0001), `unitPrice` (≥0.01, siempre sin ITBIS), `discount` y `surcharge` (monto, no %), `itbisRate` (0/16/18, por defecto 18), `indicadorFacturacion` (0–4; 4 = exento), `goodService` (1/2), `code`, `unit`, `additionalTaxCode`/`Rate` |
| `payment` | `type` 1–3 (obligatorio), `method` 1–8, `date`, `termDays` (obligatorio si `type=2`, 1–365), datos de cuenta |
| `reference` | `encf` (serie E, B o A/P), `date` DD-MM-YYYY, `modificationCode` 1–5, `reason` (se corta a 90 en el XML) |
| `currency` | `code` (17 monedas DGII), `exchangeRate` |

**Reglas por tipo**

| Tipo | Regla en el código |
|---|---|
| E31 | `buyer.rnc` obligatorio |
| E32 | RNC opcional. Si el total es < 250 000 se envía solo el resumen (RFCE): sin `trackId` y con resultado inmediato. La API no exige identificación del comprador en ≥ 250 000 |
| E33 / E34 | `reference` obligatoria. La nota espera hasta 24 h a que el e-CF referido sea aceptado y falla si este terminó rechazado; si la referencia no está en la plataforma (serie B), se envía. E34 no lleva formas de pago |
| E41 | El `buyer` es el proveedor (RNC obligatorio). El bloque de retención sale sin montos, porque el DTO no los acepta |
| E43 | Sin comprador |
| E44 | RNC opcional |
| E45 | RNC obligatorio |
| E46 | `transport` y `additionalInfo` obligatorios |
| E47 | `foreignBeneficiary` obligatorio, pero ni él ni `retentionAmount` llegan al XML: solo se guardan |

**Cálculo:** el ITBIS se redondea a 2 decimales por línea y luego se suma. `FechaEmision` es siempre la fecha de hoy en hora de RD. `TipoIngresos` es siempre `01` (se omite en E33/E34).

**Estados:** `QUEUED → PROCESSING → SENT →` `ACCEPTED` | `CONDITIONAL` | `REJECTED`; además `ERROR`, `CONTINGENCY` y `VOIDED`.

**Cómo informa el resultado**
- **Webhook** (suscripción por tenant, no por empresa): cuerpo `{event, deliveryId, emittedAt, data}`.
  - Cabeceras `X-ECF-Event`, `X-ECF-Delivery-Id`, `X-ECF-Timestamp` y `X-ECF-Signature: sha256=<HMAC-SHA256(secret, cuerpo)>`.
  - `data` solo trae `invoiceId`, `encf`, `trackId`, `message`; no trae empresa, estado, total ni clave de idempotencia.
  - 5 intentos (30 s, 2 min, 10 min, 1 h). La suscripción se desactiva sola tras 10 fallos en 24 h.
- **Consulta:** `GET /invoices/:id`. `POST /invoices/:id/poll` consulta a la DGII y da 400 si no hay `trackId` (caso RFCE).
- **Documentos:** `GET /invoices/:id/xml` devuelve el XML sin firmar si aún no hay firmado, así que hay que mirar `hasSignedXml`. `GET /invoices/:id/pdf` devuelve 409 hasta que se firme.
- **Otros:** `POST /invoices/:id/void` (solo DRAFT, ERROR, CONTINGENCY, REJECTED), `/sequences/:companyId/annulable`, `/contingency/:id/retry`, `/received`.

**Idempotencia:** la clave es única por tenant. Repetir el POST devuelve la factura existente con 202, sin comparar el contenido. No existe consulta por clave.

**Ambientes**

| Ambiente | Envía a la DGII | Cuota | Overrides |
|---|---|---|---|
| DEV | Sí, a `ecf.dgii.gov.do/testecf` (no hay simulador) | No cuenta | Permitidos |
| CERT | Sí, a `…/certecf` | No cuenta | Permitidos |
| PROD | Sí, a `…/ecf` | Cuenta | 403 |

**La guía (`INTEGRATION_GUIDE.md`) no coincide con el código en tres puntos:**
- La tabla de tipos está cruzada: el código usa E41 = Compras, E43 = Gastos menores, E44 = Regímenes especiales, E45 = Gubernamental.
- El webhook documentado trae `tenantId`, `timestamp` y eventos `invoice.accepted`; el real trae `deliveryId`, `emittedAt` y el enum `INVOICE_ACCEPTED`.
- El prefijo de clave documentado es `ecf_`; `.env.example` dice `frd`.

**SIN VERIFICAR**
- Si los `Decimal` llegan en el JSON como texto o como número.
- Si la DGII rechaza un E32 ≥ 250 000 sin identificación del comprador.
- Cómo trata la DGII una E34 de más de 30 días que lleva ITBIS (el indicador se calcula, pero el ITBIS no se quita).
- El comportamiento exacto de `/contingency/:id/retry` (solo leí la ruta y el inicio del servicio).

## 2. Mapeo `account.move` → API

| Dato | Odoo | API | Falta |
|---|---|---|---|
| Emisor | `company_id` | Sale de la empresa registrada en la plataforma, no del request | Odoo: guardar `companyId` y validar que el RNC coincide. Municipio y provincia DGII no existen en Odoo |
| Tipo | `l10n_do_ncf_type_id.code` | 01→E31, 02→E32, 03→E33, 04→E34, 14→E44, 15→E45, 16→E46, 11→E41, 13→E43, 17→E47 | Odoo nunca asigna tipos E hoy (ver punto 3). B12 no tiene equivalente |
| Comprador | `partner_id.vat` (solo dígitos), `name`, `email`, `street` | `buyer.rnc`, `name`, `email`, `address` | Códigos de municipio/provincia. Identificación extranjera: `foreignId` no está en el DTO |
| Línea | `name`, `quantity`, `price_unit`, `default_code`, tipo de producto | `description`, `quantity`, `unitPrice`, `code`, `goodService` | Con impuesto incluido en precio hay que derivar la base. La API rechaza precio 0 y líneas negativas (anticipos, descuentos como línea) |
| Descuento | `discount` (%) | `discount` (monto) | Convertir. Descuento global: `discountsOrSurcharges` no está en el DTO |
| ITBIS 18 / 16 | `tax_ids.amount` | `itbisRate` 18 o 16 | — |
| ITBIS 0 % y exento | Ambos son un impuesto al 0 % | `indicadorFacturacion` 3 o 4 | Odoo: campo en `account.tax` para distinguirlos. Sin impuesto, la API asume 18 % |
| ISC, propina, CDT | Montos manuales en la factura (`l10n_do_propina_legal`, etc.) | `additionalTaxCode`/`Rate` por línea | Odoo no los tiene por línea |
| Retenciones | `l10n_do_retention_ids`, impuestos negativos | Solo `retentionAmount`, que no va al XML | ecf-api: el constructor de XML ya las soporta; el DTO no las expone |
| Tipo de pago | `invoice_date_due` frente a `invoice_date` | `type` 1/2, `termDays`, `date` | Plazo mayor de 365 días se rechaza |
| Forma de pago | `l10n_do_forma_pago` (códigos del 607) | `method`: 01→1, 02→2, 03→3, 04→4, 05→6, 06→7, 07→8 | Al confirmar la factura no está pagada, así que siempre sale "crédito". Pago mixto: `payment.forms` no está en el DTO. El cálculo de Odoo ignora bonos |
| Tipo de ingreso | No existe (el 607 lo fija en el asistente) | No está en el DTO | Ambos lados |
| Moneda y tasa | `currency_id`, `l10n_do_exchange_rate` (por defecto 1.0) | `currency.code`, `exchangeRate` | El constructor asume precios en DOP y divide por la tasa: Odoo debe convertir a DOP antes de enviar. La moneda debe estar entre las 17 de la DGII |
| Fecha de emisión | `invoice_date` | No se acepta; siempre hoy | ecf-api, o bloquear en Odoo fechas distintas de hoy |
| NCF modificado | `l10n_do_ncf_origin`, `l10n_do_debit_ncf_origin`, fecha de la factura origen | `reference.encf`, `date` | Si el origen se escribió a mano sin factura enlazada, falta la fecha |
| Código de modificación | `l10n_do_credit_note_reason` (01–06, lista propia) | `modificationCode` 1–5 | No son equivalentes. Propongo un campo nuevo con los 5 códigos DGII; por defecto 01→1 y el resto→3 |
| Total | `amount_total` | `totalAmount` de la respuesta y `MontoTotal` del XML | `amount_total` resta las retenciones y el e-CF no: comparar contra base + ITBIS, en DOP |

## 3. Numeración

**Estado actual:** las secuencias E31–E47 ya son inalcanzables desde las facturas.
- `_compute_l10n_do_ncf_type_id` solo devuelve códigos B, y el campo es de solo lectura.
- El POS solo admite secuencias B.
- Por eso "desactivar" consiste en hacer el cambio de tipo explícito y bloquear las secuencias E.

**Propuesta**
1. **Activación por compañía:** `l10n_do_ecf_provider` (`none`/`newplain`) más fecha de inicio, y marca por diario para que un diario de contingencia siga en papel.
2. **Dos puntos de extensión en `l10n_do_ncf`:** un método `_l10n_do_get_ncf_type_code()` que el conector sobrescribe para convertir B→E, y una salida temprana en `_generate_ncf()` cuando la numeración es externa.
3. **Bloqueo de secuencias locales:** crear o activar una secuencia electrónica en esa compañía da error; las que existan se archivan, no se borran. Las secuencias B no se tocan.
4. **El e-NCF no se escribe en la factura hasta ACCEPTED o CONDITIONAL.** Mientras tanto vive en un modelo propio (`l10n_do_ecf.document`: factura, intento, clave, e-NCF, estado, trackId).
   - Motivo: `write()` y `unlink()` protegen la factura en cuanto tiene NCF. Un número rechazado la dejaría bloqueada.
   - El prefijo coincide con el tipo E, así que `_lock_ncf_type_after_generation` pasa.
5. **Notas sobre facturas en papel:** una E34 puede referir un B01. La API acepta el formato y la envía sin esperar.

Hay que enganchar `_post()` y no `action_post()`, porque el POS confirma con `_post()`.

## 4. Diseño del conector

- **Configuración:** modelo `l10n_do_ecf.connection` con URL, API key y secreto del webhook, visibles solo para `base.group_system`. Va separado de la compañía porque el webhook es por tenant y varias compañías pueden compartirlo. La compañía guarda la conexión, el `companyId` y el ambiente (leído de la plataforma, no elegido en Odoo). Scopes mínimos: `INVOICES_WRITE`, `INVOICES_READ`, `COMPANIES_READ`, `SEQUENCES_READ`.
- **Envío:** al confirmar se crea el documento en `to_send` con clave `odoo-<db>-<move_id>-<intento>`, y se envía después del commit (con cron de respaldo y botón manual). Enviar dentro de la transacción de confirmación dejaría un e-CF huérfano en la DGII si Odoo revierte. Un timeout se resuelve repitiendo el POST con la misma clave.
- **Validación previa en Odoo:** fecha igual a hoy, sin líneas negativas ni de precio 0, cada línea con su clasificación de ITBIS, RNC según tipo, moneda admitida, tasa distinta de 1.
- **Webhook:** ruta pública que lee el cuerpo crudo y compara el HMAC con `hmac.compare_digest`.
  - Descarta duplicados por `deliveryId`.
  - Responde 200 a facturas desconocidas, porque el tenant puede tener otros sistemas.
  - No confía en el contenido: hace `GET /invoices/:id` y actualiza desde ahí.
- **Consulta de respaldo:** cron cada 5 min sobre documentos no finales con `GET /invoices/:id`. Es imprescindible, porque la suscripción se desactiva sola si Odoo estuvo caído.
- **Aceptación:** descarga XML y PDF, los adjunta, lee `MontoTotal` del XML y lo compara con Odoo. Si difiere, marca la factura y crea una actividad para contabilidad. Luego escribe el e-NCF y pone el estado fiscal en `valid`.
- **Rechazo:** estado fiscal `rejected` y mensaje de la DGII en el chatter. El e-NCF muerto queda en el documento. Reenviar crea un intento nuevo con clave nueva, y la plataforma asigna otro número.
- **Bloqueos:** con un e-CF en vuelo o aceptado no se permite volver a borrador ni la anulación directa del asistente (que cancela por SQL); solo nota de crédito.

**Cambios necesarios en ecf-api**

| Para | Cambio |
|---|---|
| Fase 1 | Aceptar `fechaEmision`, `incomeType`, `discountsOrSurcharges` y `payment.forms` en el DTO (el constructor ya los soporta) |
| Fase 1 | `expectedTotalAmount`: rechazar con 422 dentro de la transacción si no cuadra. Hoy la diferencia solo se ve cuando el número ya se consumió y el envío está en cola |
| Fase 1 | Consulta por clave de idempotencia, y 409 si se repite la clave con contenido distinto |
| Fase 1 | Webhook: incluir `companyId`, `status`, `totalAmount` e `idempotencyKey`; firmar también el timestamp; avisar o exponer la desactivación automática |
| Fase 1 | Corregir la guía (tipos, eventos, prefijo); documentar que los montos van en DOP |
| Fase 2 | Retenciones por línea y totales; llevar `foreignBeneficiary` y la retención al XML del E47; `buyer.foreignId`; exigir identificación en E32 ≥ 250 000; límite de peticiones por clave en vez de por IP |
| Fase 3 | `GET /received/:id` con el XML, filtro por empresa y paginación (hoy devuelve como máximo 100, de todo el tenant) |

## 5. Los 5 problemas de `l10n_do_ncf`

| Problema | Hallazgo | ¿Antes de construir? |
|---|---|---|
| Modelo duplicado | Los dos archivos son idénticos byte a byte y ambos se importan: tres modelos definidos dos veces | Sí, es trivial: borrar `models/fiscal_reconciliation.py` y su import |
| `tax_dgii_config.xml` fuera del manifest | Confirmado; es redundante con `__init__.py` | Sí, por lo que arrastra (ver abajo) |
| README y residuos | El README dice Odoo 17. `static/l10n_do_ncf_17.0.1.6.0.zip` está versionado dentro de `static/`, que Odoo sirve públicamente. `setup_wizard_views.xml.save` está vacío | El zip sí; el resto puede esperar |
| Modelos sin vistas | `dgii.txt.validator` y `dgii.reminder` no tienen vista; `move.retention` no tiene vista propia | No |
| Sin tests | No hay carpeta `tests` | Sí, lo mínimo: tests de la selección de tipo, `_generate_ncf`, origen de NC y la ruta del POS antes de refactorizarlos |

**Hallazgo adicional, más grave que los cinco:** `hooks.py` es código muerto.
- El manifest apunta a `post_init_hook`, que se resuelve en `__init__.py`; `hooks.py` nunca se importa.
- Por eso no se crean los índices únicos de NCF por compañía ni los impuestos "Exento" que ese archivo define.
- El conector necesita ambos: la unicidad del e-NCF y distinguir exento de 0 %. Hay que resolverlo antes.
- SIN VERIFICAR si el índice existe en vuestra base por otra vía, y cómo trata Odoo 19 la doble definición de un modelo.

## Fases y esfuerzo (un desarrollador que conozca ambos repos)

| Bloque | Alcance | Días |
|---|---|---|
| Previo en `l10n_do_ncf` | Limpieza, hooks, índice, campo de clasificación de ITBIS, puntos de extensión, tests | 3–4 |
| ecf-api, fase 1 | Cambios de la tabla anterior | 4–6 |
| Fase 1 | E31, E32 ≥ 250 000, E33, E34: configuración, payload, envío, webhook, cron, adjuntos, bloqueos, tests con HTTP simulado | 12–15 |
| Pruebas fase 1 | Extremo a extremo en DEV y CERT | 3–4 |
| Fase 2 | POS E32 < 250 000, E41, E43–E47, más ecf-api | 18–23 |
| Fase 3 | Facturas recibidas y aprobación comercial, más ecf-api | 11–14 |

Total aproximado: 10–13 semanas; la fase 1 completa, 4–6 semanas.
