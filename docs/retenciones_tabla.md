# Impuestos de retención: tabla para confirmar con el contador

Desde la versión 19.0.4 la retención de una compra **es el impuesto de retención
de la línea** (el que genera el asiento: pasivo con la DGII y menos por pagar al
proveedor). El 606, el IR-17, el 609 y el e-CF (E41/E47) salen de esos impuestos.

Esta tabla reúne los impuestos de retención que trae hoy el plan contable
`l10n_do` de Odoo y los tipos de retención que usaba el módulo en la pestaña
"Retenciones". **Nada de lo marcado "a confirmar" se aplica solo**: la
configuración automática no crea impuestos de retención y solo pone el tipo de
retención ISR del 606 (casilla 17) donde el impuesto es inequívoco.

## 1. Impuestos de retención del plan `l10n_do`

Columnas:
- **Tasa en Odoo**: el porcentaje del impuesto sobre la base (sin ITBIS). Una
  retención del 100 % del ITBIS es −18 % de la base; la del 30 %, −5.4 %.
- **Tipo DGII**: ITBIS o ISR (campo "Tipo Retención DGII"); ya lo asigna la
  configuración automática.
- **Tipo 606 ISR**: casilla 17 del 606 (01 Alquileres, 02 Honorarios por
  servicios, 03 Otras rentas, 04 Otras rentas presuntas, 05 Intereses a
  personas jurídicas, 06 Intereses a personas físicas, 07 Proveedores del
  Estado, 08 Juegos telefónicos). Solo aplica a las de ISR.

| Impuesto (plantilla) | Nombre | Tasa en Odoo | Cuenta | Tipo DGII | Tipo 606 ISR propuesto | Estado |
|---|---|---|---|---|---|---|
| `ret_100_tax_person` | Retención 100% ITBIS Servicios a Físicas (R293-11) | −18 % (100 % del ITBIS) | 21030202 ITBIS Retenido a Persona Física | ITBIS | — | Tipo DGII asignado |
| `ret_100_tax_security` | Retención 100% ITBIS Servicios de Seguridad (N07-09) | −18 % | 21030201 ITBIS Retenido a Persona Jurídica | ITBIS | — | Tipo DGII asignado |
| `ret_100_tax_nonprofit` | Retención 100% ITBIS Servicios No Lucrativas (N01-11) | −18 % | 21030203 ITBIS Retenido a Entidades No Lucrativas | ITBIS | — | Tipo DGII asignado |
| `ret_30_tax_moral` | Retención 30% ITBIS Servicios a Jurídicas (N02-05) | −5.4 % | 21030201 ITBIS Retenido a Persona Jurídica | ITBIS | — | Tipo DGII asignado |
| `ret_30_tax_freelance` | Retención 30% ITBIS Servicios Profesionales (N02-05) | −5.4 % (inactivo en la plantilla) | 21030201 | ITBIS | — | Tipo DGII asignado |
| `ret_75_tax_nonformal` | Retención 75% ITBIS Bienes a Informales (N08-10) | −13.5 % | 21030205 ITBIS Retenido a Informales de Bienes | ITBIS | — | Tipo DGII asignado |
| `ret_15_income_person` | Retención 15% ISR Honorarios a Físicas | −15 % | 21030301 ISR Retenido por Honorarios de Personas Físicas | ISR | **02** | **Asignado (inequívoco)** |
| `ret_15_income_rent` | Retención 15% ISR Alquileres a Físicas | −15 % | 21030302 ISR Retenido por Alquileres a Personas Físicas | ISR | **01** | **Asignado (inequívoco)** |
| `ret_10_income_dividend` | Retención 10% ISR por Dividendos (L253-12) | −10 % | 21030303 ISR Retenido por Dividendos | ISR | — (no es una compra) | A confirmar |
| `ret_3_income_person` | Retención 3% ISR conforme a la Norma 07-2007 (L30-26) | −3 % | 21030308 Otras Retenciones (N07-07) | ISR | 03 | A confirmar |
| `ret_3_income_article_70` | Retención 3% ISR por Otras Rentas (Decreto 139-98, Art. 70) | −3 % | 21030309 Otras Retenciones | ISR | 03 | A confirmar |
| `ret_2_income_transfer` | Retención 2% ISR por Transferencias de Títulos y Propiedades | −2 % | 21030306 ISR Retenido por Transferencias | ISR | 03 | A confirmar |
| `ret_27_income_remittance` | Retención 27% ISR por Remesas al Exterior (L253-12) | −27 % | 21030307 ISR Retenido por Remesas al Exterior | ISR | 03 (lo que el módulo ponía en un pago al exterior); va además en el 609 | **Sugerido en el pago al exterior** (Guía del Contribuyente No. 5, pág. 5; arts. 297 y 305 del Código Tributario); editable por convenios. Tipo 606 a confirmar |
| `ret_15_income_foreign_royalties_technology` | Retención 15% ISR por Regalías, Licencias de Software, Publicidad en Línea y Datos en el Exterior (L30-26) | −15 % | 21030310 ISR Retenido por Regalías y Servicios Tecnológicos del Exterior | ISR | 03; va además en el 609 | A confirmar |
| `ret_5_income_gov` | Retención 5% ISR Gubernamentales (ventas) | −5 % | 11080302 | ISR | — (nos la retiene el Estado: 607, no 606) | No aplica |

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
| `ISR_PROF` | ISR Servicios Profesionales (10%) | 10 % | Ninguno al 10 %: la plantilla trae honorarios al **15 %** (`ret_15_income_person`) | **Tasa a confirmar** |
| `ISR_TEC` | ISR Servicios Técnicos (2%) | 2 % | `ret_2_income_transfer` es "Transferencias de títulos": **no** equivale por nombre | A confirmar |
| `ISR_ALQ` | ISR Alquileres Persona Física (10%) | 10 % | Ninguno al 10 %: la plantilla trae alquileres al **15 %** (`ret_15_income_rent`) | **Tasa a confirmar** |
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
