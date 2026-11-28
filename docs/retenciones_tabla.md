# Impuestos de retención: tabla para confirmar con el contador

Desde la versión 4.x la retención de una compra **es el impuesto de retención
de la línea** (el que genera el asiento: pasivo con la DGII y menos por pagar al
proveedor). El 606, el IR-17, el 609 y el e-CF (E41/E47) salen de esos impuestos.

Esta tabla reúne los impuestos de retención que trae hoy el plan contable
`l10n_do` de Odoo y los tipos de retención que usaba el módulo en la pestaña
"Retenciones". **Nada de lo marcado "a confirmar" se aplica solo**: la
configuración automática no crea impuestos de retención, y en Odoo 16 tampoco
asigna el tipo de retención ISR del 606 (casilla 17): lo confirma el contador
(ver el final de la sección 1).

## 1. Impuestos de retención del plan `l10n_do`

> **Odoo 16.** Esta tabla es la del plan `l10n_do` que trae Odoo **16.0**
> (`addons/l10n_do/data/account.tax.template.xml`). No es la misma que en la
> 19: las retenciones de ISR de honorarios y alquileres están al **10 %**, no
> al 15 %, y el plan de 16 no trae `ret_3_income_person`,
> `ret_3_income_article_70` ni `ret_15_income_foreign_royalties_technology`.

Columnas:
- **Tasa en Odoo**: el porcentaje del impuesto sobre la base (sin ITBIS). Una
  retención del 100 % del ITBIS es −18 % de la base; la del 30 %, −5.4 %.
- **Tipo DGII**: ITBIS o ISR (campo "Tipo Retención DGII"); ya lo asigna la
  configuración automática.
- **Tipo 606 ISR**: casilla 17 del 606 (01 Alquileres, 02 Honorarios por
  servicios, 03 Otras rentas, 04 Otras rentas presuntas, 05 Intereses a
  personas jurídicas, 06 Intereses a personas físicas, 07 Proveedores del
  Estado, 08 Juegos telefónicos). Solo aplica a las de ISR.

| Impuesto (plantilla) | Nombre en el plan de 16 | Tasa en Odoo | Uso | Tipo DGII | Tipo 606 ISR propuesto | Estado |
|---|---|---|---|---|---|---|
| `ret_100_tax_person` | Retención 100% ITBIS Servicios a Físicas (R293-11) | −18 % (100 % del ITBIS) | compras | ITBIS | — | Tipo DGII asignado |
| `ret_100_tax_security` | Retención 100% ITBIS Servicios de Seguridad (N07-09) | −18 % | compras | ITBIS | — | Tipo DGII asignado |
| `ret_100_tax_nonprofit` | Retención 100% ITBIS Servicios No Lucrativas (N01-11) | −18 % | compras | ITBIS | — | Tipo DGII asignado |
| `ret_30_tax_moral` | Retención 30% ITBIS Servicios a Jurídicas (N02-05) | −5.4 % | compras | ITBIS | — | Tipo DGII asignado |
| `ret_30_tax_freelance` | Retención 30% ITBIS Servicios Profesionales (N02-05) | −5.4 % | ninguno (`type_tax_use = none`) | ITBIS | — | Tipo DGII asignado; no se puede usar en una línea tal como viene |
| `ret_75_tax_nonformal` | Retención 75% ITBIS Bienes a Informales (N08-10) | −13.5 % | compras | ITBIS | — | Tipo DGII asignado |
| `ret_10_income_person` | Retención 10% ISR Honorarios a Físicas | −10 % | compras | ISR | 02 | **A confirmar** (en la 19 se asignaba solo, con la plantilla al 15 %) |
| `ret_10_income_rent` | Retención 10% ISR Alquileres a Físicas | −10 % | compras | ISR | 01 | **A confirmar** (en la 19 se asignaba solo, con la plantilla al 15 %) |
| `ret_10_income_dividend` | Retención 10% ISR por Dividendos (L253-12) | −10 % | compras | ISR | — (no es una compra) | A confirmar |
| `ret_2_income_person` | Retención 2% ISR a Física (con Materiales) | −2 % | compras | ISR | 03 | A confirmar |
| `ret_2_income_transfer` | Retención 2% ISR por Transferencia de Títulos | −2 % | compras | ISR | 03 | A confirmar |
| `ret_27_income_remittance` | Retención 27% ISR por Remesas al Exterior (L253-12) | −27 % | compras | ISR | 03 (lo que el módulo ponía en un pago al exterior); va además en el 609 | **Sugerido en el pago al exterior** (Guía del Contribuyente No. 5, pág. 5; arts. 297 y 305 del Código Tributario); editable por convenios. Tipo 606 a confirmar |
| `ret_5_income_gov` | Retención 5% ISR Gubernamentales | −5 % | ventas | ISR | — (nos la retiene el Estado: 607, no 606) | No aplica |

### Por qué en 16 ninguna lleva tipo 606 automático

En la 19, la configuración automática ponía el tipo 606 en honorarios (02) y
alquileres (01) porque las plantillas `ret_15_income_person` y
`ret_15_income_rent` lo dicen sin ambigüedad. El plan de 16 no las tiene: las
suyas son `ret_10_income_person` y `ret_10_income_rent`, con otra tasa. Para no
inventar nada, **en 16 no se asigna ningún tipo 606 de ISR**: todas las
retenciones de ISR de compras aparecen en la tarjeta "Configuración pendiente"
del Panel (grupo `taxes_isr_type`) hasta que el contador las confirme una a una
en el impuesto.

## 2. Tipos de retención que usaba el módulo (pestaña "Retenciones")

Para convertir las facturas en **borrador** que aún tienen retenciones escritas en
la pestaña, cada tipo necesita su impuesto equivalente (campo "Impuesto de
retención equivalente" del tipo de retención). Al indicarlo, esos borradores se
convierten solos si el monto da igual; si no, se quedan para revisar. Las
facturas **confirmadas** no se tocan nunca: se ajustan a mano desde la lista del
Panel.

| Código | Nombre en el módulo | Tasa del módulo | Impuesto equivalente propuesto | Observación |
|---|---|---|---|---|
| `ITBIS_100` | ITBIS Compra Informal (100%) | 100 % del ITBIS | `ret_100_tax_person` | A confirmar |
| `ITBIS_PF` | ITBIS Persona Física (100%) | 100 % del ITBIS | `ret_100_tax_person` | A confirmar |
| `ITBIS_PROF` | ITBIS Servicios Profesionales (30%) | 30 % del ITBIS | `ret_30_tax_moral` o `ret_30_tax_freelance` | A confirmar cuál |
| `ITBIS_75` | ITBIS Grandes Contribuyentes (75%) | 75 % del ITBIS | `ret_75_tax_nonformal` es "Bienes a Informales": **no** equivale por nombre | A confirmar |
| `ITBIS_EST` | ITBIS Proveedores del Estado (100%) | 100 % del ITBIS | Ninguno en la plantilla | A confirmar |
| `ISR_PROF` | ISR Servicios Profesionales (10%) | 10 % | `ret_10_income_person` (Honorarios a Físicas, −10 %) | Coincide la tasa; confirmar el tipo 606 |
| `ISR_TEC` | ISR Servicios Técnicos (2%) | 2 % | `ret_2_income_transfer` es "Transferencias de títulos": **no** equivale por nombre | A confirmar |
| `ISR_ALQ` | ISR Alquileres Persona Física (10%) | 10 % | `ret_10_income_rent` (Alquileres a Físicas, −10 %) | Coincide la tasa; confirmar el tipo 606 |
| `ISR_EXT` | ISR Pagos al Exterior (27%) | 27 % | `ret_27_income_remittance` | Misma tasa y concepto; a confirmar |
| `ISR_EST` | ISR Proveedores del Estado (5%) | 5 % | Ninguno de compras en la plantilla | A confirmar |
| `ISR_PERC` / `ITBIS_PERC` | Percibido (nos retuvieron / cobraron) | — | — | El e-CF no admite percepciones |

## 3. Lo que hay que decidir

1. Las tasas de ISR del módulo (10 % profesionales y alquileres, 2 % técnicos)
   frente a las de la plantilla (15 %): cuáles son las vigentes para cada caso.
2. El tipo 606 de cada impuesto de ISR marcado "A confirmar".
3. Qué impuestos se sugieren solos al **proveedor informal** (Ajustes >
   Contabilidad > "Retenciones sugeridas en compras"): vacío hasta que el
   contador lo indique. En el **pago al exterior** se sugiere el ISR 27 %
   ("-27% ISR (L253-12)"), editable.
4. El impuesto equivalente de cada tipo de retención de la sección 2, para
   convertir los borradores.
