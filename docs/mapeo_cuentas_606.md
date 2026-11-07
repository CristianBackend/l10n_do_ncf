# Mapeo de cuentas del plan l10n_do → "Tipo 606"

Qué "Tipo de bienes y servicios comprados" (casilla 3 del Formato 606) pone automáticamente `l10n_do_ncf` en cada cuenta del plan contable dominicano de Odoo 19 (`l10n_do`), y por qué algunas quedan vacías.

- **Fuente de la clasificación:** Norma General 07-2018 de la DGII, Anexo A, "Tabla de clasificación de Costos y Gastos" (qué asume cada tipo), e instructivo "Llenado y Remisión del Formato 606" (julio 2025), casilla 3.
- **Cómo se aplica:** por xmlid de la plantilla (`account.<compañía>_<plantilla>`), nunca por nombre; al instalar o actualizar el módulo y al cargar el plan `do` en una compañía. **Solo en cuentas vacías:** un valor puesto a mano nunca se cambia.
- **Cuentas vacías:** el 606 marca como pendiente cada compra registrada en ellas, hasta que se les ponga el tipo (o se indique en la factura). La tarjeta "Configuración pendiente" del Panel e-CF las cuenta.
- **Código:** `models/l10n_do_autoconfig.py`, `ACCOUNT_TEMPLATE_606`.

## Tipos de la DGII

| Código | Tipo |
|---|---|
| 01 | Gastos de personal |
| 02 | Gastos por trabajos, suministros y servicios |
| 03 | Arrendamientos |
| 04 | Gastos de activos fijos |
| 05 | Gastos de representación |
| 06 | Otras deducciones admitidas |
| 07 | Gastos financieros |
| 08 | Gastos extraordinarios |
| 09 | Compras y gastos que formarán parte del costo de venta |
| 10 | Adquisiciones de activos |
| 11 | Gastos de seguros |

## Cuentas con tipo asignado (71)

| Cuenta | Nombre | Tipo 606 | Por qué |
|---|---|---|---|
| 12010101 | Terrenos | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010102 | Edificaciones | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010103 | Mejoras en Edificaciones | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010104 | Mejoras en Edificaciones y Locales Arrendados | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010201 | Equipos de Transporte Liviano | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010202 | Mobiliarios y Equipos de Oficina | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010301 | Maquinarias | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010302 | Herramientas | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010303 | Instalaciones | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010304 | Sistemas de Cámara y Seguridad | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12010305 | Misceláneos u otros activos | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12040100 | Marcas y Patentes | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 12040200 | Licencias y Programas Informáticos | 10 Adquisiciones de activos | Compra de un activo fijo de la empresa (Anexo A, tipo 10). |
| 51010100 | Costos de Bienes | 09 Compras y gastos que formarán parte del costo de venta | Compra que se incorpora a lo vendido (Anexo A, tipo 9). |
| 51010200 | Costos de Servicios | 09 Compras y gastos que formarán parte del costo de venta | Compra que se incorpora a lo vendido (Anexo A, tipo 9). |
| 51020100 | Costos de Materia Prima | 09 Compras y gastos que formarán parte del costo de venta | Compra que se incorpora a lo vendido (Anexo A, tipo 9). |
| 51020300 | Costos Indirectos | 09 Compras y gastos que formarán parte del costo de venta | Compra que se incorpora a lo vendido (Anexo A, tipo 9). |
| 51020400 | Costos de Importación | 09 Compras y gastos que formarán parte del costo de venta | Compra que se incorpora a lo vendido (Anexo A, tipo 9). |
| 61010900 | Comidas o Dietas al Personal | 01 Gastos de personal | Pago a terceros por un beneficio del personal (Anexo A, tipo 1). |
| 61011000 | Cursos y Entrenamientos | 01 Gastos de personal | Pago a terceros por un beneficio del personal (Anexo A, tipo 1). |
| 61011400 | Uniformes | 01 Gastos de personal | Pago a terceros por un beneficio del personal (Anexo A, tipo 1). |
| 61011500 | Otros Gastos de Personal | 01 Gastos de personal | Pago a terceros por un beneficio del personal (Anexo A, tipo 1). |
| 61020100 | Energía Eléctrica | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61020200 | Comunicaciones | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61020300 | Suministros de Oficina (Papelería y útiles) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61020400 | Útiles de Aseo y Limpieza | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61020500 | Agua y Basura | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61020600 | Seguro de Edificio y Locales | 11 Gastos de seguros | Prima de seguro (Anexo A, tipo 11). |
| 61020700 | Combustibles y Lubricantes | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61020800 | Alquileres / Arrendamientos | 03 Arrendamientos | Arrendamiento de local, maquinaria o almacenamiento (Anexo A, tipo 3). |
| 61021100 | Seguros | 11 Gastos de seguros | Prima de seguro (Anexo A, tipo 11). |
| 61021200 | Servicios de Mensajería | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61021300 | Flete y Carga | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030101 | Legales (P. Física) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030102 | Contabilidad y Auditoría (P. Física) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030103 | Tecnología (P. Física) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030104 | Mantenimientos de Planta (P. Física) | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61030106 | Mantenimientos Mobiliarios y Equipos (P. Física) | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61030107 | Asesorías (P. Física) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030108 | Fumigaciones (P. Física) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030109 | Copias y Escaneos (P. Física) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030110 | Servicios de Vigilancia (P. Física) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030111 | Otros Servicios Profesionales (P. Física) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030201 | Legales (P. Jurídica) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030202 | Contabilidad y Auditoría (P. Jurídica) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030203 | Tecnología (P. Jurídica) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030204 | Mantenimiento de Planta (P. Jurídica) | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61030206 | Mantenimiento Mobiliario y Equipos (P. Jurídica) | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61030207 | Asesorías (P. Jurídica) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030208 | Fumigaciones (P. Jurídica) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030209 | Copias y Escaneos (P. Jurídica) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030210 | Servicios de Vigilancia (P. Jurídica) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030211 | Otros Servicios Profesionales  (P. Jurídica) | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030301 | Honorarios por Servicios del Exterior - Relacionadas | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61030302 | Honorarios por Servicios del Exterior - Terceros | 02 Gastos por trabajos, suministros y servicios | Servicio, suministro o trabajo contratado (Anexo A, tipo 2). |
| 61050100 | Gastos por Reparación de Edificios | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61050200 | Gastos por Reparación de Equipo de Transporte | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61050300 | Gastos por Reparación de Mobiliario y Equipos | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61050400 | Gastos por Reparación de Maquinaria | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61050500 | Gastos por Reparación de Herramientas | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61050600 | Gastos por Reparación de Instalaciones | 04 Gastos de activos fijos | Reparación o mantenimiento de un activo fijo propio (Anexo A, tipo 4). |
| 61060100 | Relaciones Públicas | 05 Gastos de representación | Relaciones públicas, publicidad o promoción (Anexo A, tipo 5). |
| 61060200 | Publicidad | 05 Gastos de representación | Relaciones públicas, publicidad o promoción (Anexo A, tipo 5). |
| 61060600 | Promociones | 05 Gastos de representación | Relaciones públicas, publicidad o promoción (Anexo A, tipo 5). |
| 61070100 | Financial Loan Expenses | 07 Gastos financieros | Comisiones, intereses o cargos de instituciones financieras (Anexo A, tipo 7). |
| 61070300 | Intereses Bancarios | 07 Gastos financieros | Comisiones, intereses o cargos de instituciones financieras (Anexo A, tipo 7). |
| 61070400 | Comisiones Bancarias | 07 Gastos financieros | Comisiones, intereses o cargos de instituciones financieras (Anexo A, tipo 7). |
| 61070500 | Comisiones de Tarjeta de Crédito | 07 Gastos financieros | Comisiones, intereses o cargos de instituciones financieras (Anexo A, tipo 7). |
| 61070600 | Cargos Bancarios | 07 Gastos financieros | Comisiones, intereses o cargos de instituciones financieras (Anexo A, tipo 7). |
| 61070700 | Seguro sobre Préstamos Bancarios | 11 Gastos de seguros | Prima de seguro (Anexo A, tipo 11). |
| 61070900 | Otro Gastos Financieros | 07 Gastos financieros | Comisiones, intereses o cargos de instituciones financieras (Anexo A, tipo 7). |

## Pendientes de revisión del contador (5)

Tenían una propuesta clara, pero se dejaron vacías hasta que el contador las revise.

| Cuenta | Nombre | Propuesta y motivo |
|---|---|---|
| 61021500 | Alojamiento en Hoteles | Pendiente de revisión del contador (decisión del 2026-11-06). Propuesta: 05 Representación (el tipo 5 incluye hospedaje). |
| 61060300 | Gastos de Viajes y Representación | Pendiente de revisión del contador (decisión del 2026-11-06). Propuesta: 05 Representación (el tipo 5 incluye viajes). |
| 61060400 | Donaciones | Pendiente de revisión del contador (decisión del 2026-11-06). Propuesta: 05 Representación (el tipo 5 incluye donaciones). |
| 61060500 | Donaciones a ProIndustria (Ley 392-07) | Pendiente de revisión del contador (decisión del 2026-11-06). Propuesta: 05 Representación (donación, Ley 392-07). |
| 61070200 | Retención por Cheques o Transferencias Electrónicas (0.15%) | Pendiente de revisión del contador (decisión del 2026-11-06). Propuesta: 07 Financieros (el tipo 7 incluye el impuesto sobre cheques y transferencias); normalmente no lleva NCF. |

## Cuentas que quedan vacías a propósito (51)

| Cuenta | Nombre | Por qué queda vacía |
|---|---|---|
| 12050100 | Edificaciones y Locales Arrendados | Activo arrendado (derecho de uso): dudoso entre 03 (arrendamiento) y 10 (activo). |
| 12050200 | Maquinarias y Equipos Arrendados | Activo arrendado (derecho de uso): dudoso entre 03 (arrendamiento) y 10 (activo). |
| 12050300 | Instalaciones Arrendadas | Activo arrendado (derecho de uso): dudoso entre 03 (arrendamiento) y 10 (activo). |
| 13010100 | Costos de Construcción en Proceso | Construcción en proceso: puede ser 10 (adquisición de activos) o costos que aún no son activo; depende del caso. |
| 51010300 | Diferencia en Precio | Diferencia en precio: asiento contable, no compra con NCF. |
| 51010500 | ITBIS llevado al Costo | ITBIS llevado al costo: es el impuesto, no una compra (va en la casilla 14 del 606). |
| 51020200 | Costos de Mano de Obra | Mano de obra: nómina, no compra con NCF. |
| 61010100 | Sueldos y Salarios | Sueldo pagado al empleado: no es compra a un tercero ni lleva NCF. El tipo 1 son pagos a terceros por beneficios "que no constituyan beneficios en efectivo pagados a los empleados". |
| 61010102 | Contribución a la Administradora de Fondos de Pensiones (AFP) | Aporte a la Seguridad Social (TSS): no es compra con NCF. |
| 61010103 | Contribución al Seguro Riesgo Laboral (SRL) | Aporte a la Seguridad Social (TSS): no es compra con NCF. |
| 61010104 | Contribución al Seguro Familiar de Salud (SFS) | Aporte a la Seguridad Social (TSS): no es compra con NCF. |
| 61010200 | Regalía Pascual | Pago en efectivo al empleado (regalía pascual): no lleva NCF. |
| 61010201 | Contribución a la Administradora de Riesgos de Salud (ARS) | Aporte a la Seguridad Social: no es compra con NCF. |
| 61010202 | Contribución a Seguros del Personal | Seguro del personal: dudoso entre 01 (beneficio al personal) y 11 (seguros); el tipo 6 los excluye expresamente. |
| 61010203 | Contribución a Planes Complementarios de Salud | Plan de salud del personal: dudoso entre 01 y 11. |
| 61010204 | Contribución Seguros de Vida | Seguro de vida del personal: dudoso entre 01 y 11. |
| 61010205 | Contribución al INFOTEP | Aporte al INFOTEP: contribución legal, no compra con NCF. |
| 61010300 | Retribuciones Complementarias | Pago en efectivo al empleado: no lleva NCF. |
| 61010400 | Bono Vacacional | Pago en efectivo al empleado: no lleva NCF. |
| 61010500 | Bono por Desempeño | Pago en efectivo al empleado: no lleva NCF. |
| 61010600 | Comisiones a Empleados | Pago en efectivo al empleado: no lleva NCF. |
| 61010700 | Indemnizaciones | Indemnización laboral pagada al empleado: no lleva NCF. (El tipo 8 cita indemnizaciones, pero que requieran comprobante.) |
| 61010800 | Bonificaciones y Gratificaciones | Pago en efectivo al empleado: no lleva NCF. |
| 61011100 | Prestaciones Laborales (Preaviso y Cesantia) | Prestaciones laborales pagadas al empleado: no llevan NCF. |
| 61011200 | Incentivos | Pago en efectivo al empleado: no lleva NCF. |
| 61011300 | Horas Extras | Pago en efectivo al empleado: no lleva NCF. |
| 61020900 | Franquicias | Franquicias: puede ser 02 (servicio) u 8 en el 609; depende del contrato. |
| 61021000 | Eventos | Eventos: puede ser 05 (representación) o 02 (servicio); depende del evento. |
| 61021400 | Cuotas y Suscripciones | Cuotas y suscripciones: 06 si es membresía en asociación empresarial o cámara; 02 si es una suscripción a un servicio. |
| 61030105 | Mantenimientos de Local (P. Física) | Mantenimiento de local: 04 solo si el local es un activo propio; si es alquilado, 02. |
| 61030205 | Mantenimiento del Local (P. Jurídica) | Mantenimiento de local: 04 solo si el local es un activo propio; si es alquilado, 02. |
| 61040100 | Gastos por Depreciación de Edificios | Depreciación: asiento contable, no compra con NCF. |
| 61040200 | Gastos por Depreciación de Equipo de Transporte | Depreciación: asiento contable, no compra con NCF. |
| 61040300 | Gastos por Depreciación de Mobiliario y Equipos | Depreciación: asiento contable, no compra con NCF. |
| 61040400 | Gastos por Depreciación de Maquinaria | Depreciación: asiento contable, no compra con NCF. |
| 61040500 | Gastos por Depreciación de Herramientas | Depreciación: asiento contable, no compra con NCF. |
| 61040600 | Gastos por Depreciación de Mobiliario y Equipos | Depreciación: asiento contable, no compra con NCF. |
| 61060700 | Gastos en Restaurantes | Gastos en restaurantes: 05 si es atención a clientes; 01 si es comida del personal. |
| 61070800 | Pérdidas por Diferencia Cambiaria | Diferencia cambiaria: asiento contable, no compra con NCF. |
| 61080100 | Pérdidas por Faltante en Caja | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 61080200 | Pérdidas por Ventas de Activos Fijos | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 61080300 | Pérdidas por Cuentas Incobrables | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 61080500 | Impuestos a los Activos | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 61080600 | Gastos por Penalidades/Recargos de DGII | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 61080700 | Gastos por Penalidades/Recargos de TSS | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 61080800 | Gastos sin Comprobantes | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 61080900 | Gastos No Deducibles | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 61081000 | Pérdida por descuento | Pérdidas, penalidades o gastos no deducibles: no son compras clasificables en el 606. |
| 71010100 | Ganancias o Pérdidas | Cuenta de resultados del ejercicio: asiento de cierre, no compra con NCF. |
| 71020100 | Gastos por Impuestos | Gasto por impuestos: pago a la DGII, no compra con NCF. |
| 71020200 | Gastos por ISR | Gasto por ISR: pago a la DGII, no compra con NCF. |

## Nota sobre el tipo 06 y el 11

La Norma incluye "primas de seguros" en el tipo 6 (Otras deducciones admitidas) y también en el 11 (Gastos de seguros, "de todo tipo"). Se usó el 11, que es el tipo específico. Ninguna cuenta del plan corresponde con claridad al 06.
