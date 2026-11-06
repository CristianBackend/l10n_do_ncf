# -*- coding: utf-8 -*-
# Migración 19.0.3.3.0
#
# La clasificación anterior de los pagos al exterior
# (l10n_do_exterior_service_type) no era la del Formato 609. Se pasa a los dos
# campos oficiales (Norma General 07-2018, Anexo D) SOLO donde la equivalencia
# es clara; lo demás queda vacío y el 609 lo marca como pendiente:
#
#   02 Servicios profesionales -> Tipo 2; Detalle 21 (persona moral) o 22
#                                 (persona física), según el contacto.
#   03 Regalías                -> Tipo 8; Detalle vacío (marca, know-how,
#                                 patente u otras: no se sabe cuál).
#   04 Intereses               -> Tipo 6; Detalle vacío (depende de con quién
#                                 es el préstamo).
#   01 Servicios técnicos, 05 Dividendos, 06 Otros -> vacíos: no tienen
#                                 equivalente en las tablas del 609.
#
# El valor anterior se conserva.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE account_move m
           SET l10n_do_609_service_type = '2',
               l10n_do_609_service_detail = CASE WHEN p.is_company THEN '21' ELSE '22' END
          FROM res_partner p
         WHERE p.id = m.commercial_partner_id
           AND m.l10n_do_exterior_service_type = '02'
           AND m.l10n_do_609_service_type IS NULL
    """)
    professional = cr.rowcount
    cr.execute("""
        UPDATE account_move
           SET l10n_do_609_service_type = CASE l10n_do_exterior_service_type
                                              WHEN '03' THEN '8' WHEN '04' THEN '6' END
         WHERE l10n_do_exterior_service_type IN ('03', '04')
           AND l10n_do_609_service_type IS NULL
    """)
    type_only = cr.rowcount
    cr.execute("""
        SELECT count(*) FROM account_move
         WHERE l10n_do_exterior_service_type IN ('01', '05', '06')
           AND l10n_do_609_service_type IS NULL
    """)
    pending = cr.fetchone()[0]
    _logger.info(
        'l10n_do_ncf 19.0.3.3.0: 609 migrado: %s con tipo y detalle, %s solo con tipo, '
        '%s sin equivalencia (quedan pendientes).', professional, type_only, pending)
