# -*- coding: utf-8 -*-
"""Barrido de las VISTAS contra el registro de Odoo.

Odoo ya comprueba al instalar que cada <field name="X"> de una vista exista en
su modelo (si no, ParseError). Lo que NO comprueba son los dominios escritos en
la vista: se evaluan en el navegador, asi que un nombre mal escrito no da error,
simplemente no filtra nunca. Eso es lo que se revisa aqui:

- domain="..." de un <field name="F"> relacional  -> contra el comodel de F
- domain="..." de un <filter>, <record> o <field> -> contra el modelo de la vista
- <field name="X"> anidados                       -> contra el modelo que toca
  (al entrar en un one2many/many2many con subvista, el modelo cambia)

Tambien repasa los <field name="X"> por si acaso: cuesta poco y asi queda
comprobado tambien lo que Odoo valida por su cuenta.
"""
import os
import re
from collections import defaultdict

from lxml import etree

env = globals()['env']

MODULOS = [r for r in os.environ.get(
    'BARRIDO_MODULOS',
    '/mnt/extra-addons/l10n_do_ncf,/mnt/extra-addons/l10n_do_ecf_newplain').split(',') if r]

MODELOS = {}
for name in list(env.registry.models):
    try:
        rs = env[name]
    except Exception:
        continue
    MODELOS[name] = set(dir(rs)) | set(rs._fields)


def comodel(modelo, nombre):
    if modelo not in MODELOS:
        return None
    try:
        campo = env[modelo]._fields.get(nombre)
    except Exception:
        return None
    return getattr(campo, 'comodel_name', None) if campo else None


def existe(modelo, nombre):
    if modelo not in MODELOS:
        return True
    return nombre in MODELOS[modelo]


def sigue_ruta(modelo, ruta):
    actual = modelo
    for parte in ruta.split('.'):
        if actual is None or actual not in MODELOS:
            return True, None
        if parte not in MODELOS[actual]:
            return False, parte
        actual = comodel(actual, parte)
    return True, None


# nombres que un dominio puede usar y no son campos
PALABRAS = {'True', 'False', 'None', 'uid', 'user', 'company_id', 'context_today',
            'today', 'datetime', 'time', 'relativedelta', 'active_id', 'active_ids',
            'allowed_company_ids', 'parent', 'id', '&', '|', '!', 'in', 'not in',
            '=', '!=', '>', '<', '>=', '<=', 'like', 'ilike', 'child_of', '=like',
            '=ilike', 'parent_of', 'any', 'not any'}

# Un campo de dominio es el PRIMER elemento de la tupla, es decir el nombre al
# que le sigue una coma y un operador. Sin exigir el operador se cuela tambien
# el valor: ('move_type', 'in', ('out_invoice', 'out_refund')).
OPERADORES = ('=', '!=', '>', '<', '>=', '<=', 'in', 'not in', 'like', 'ilike',
              'not like', 'not ilike', '=like', '=ilike', 'child_of', 'parent_of',
              'any', 'not any', '!=?', '=?')
CAMPO_EN_DOMINIO = re.compile(
    r"""['"]([A-Za-z_][A-Za-z0-9_.]*)['"]\s*,\s*['"](?:%s)['"]"""
    % '|'.join(re.escape(op) for op in OPERADORES))

hallazgos = defaultdict(list)


def revisa_dominio(texto, modelo, fichero, linea, de_donde):
    for nombre in set(CAMPO_EN_DOMINIO.findall(texto or '')):
        if nombre in PALABRAS:
            continue
        ok, falla = sigue_ruta(modelo, nombre)
        if not ok:
            hallazgos[('dominio de %s' % de_donde, falla)].append(
                (fichero, linea, '%s -> %s' % (modelo, nombre)))


def recorre(nodo, modelo, fichero):
    """Recorre el arch de una vista llevando el modelo del contexto."""
    for hijo in nodo:
        if not isinstance(hijo.tag, str):
            continue
        siguiente = modelo
        if hijo.tag == 'field':
            nombre = hijo.get('name')
            if nombre and modelo:
                if not existe(modelo, nombre):
                    hallazgos[('field de la vista', nombre)].append(
                        (fichero, hijo.sourceline, modelo))
                else:
                    hijo_modelo = comodel(modelo, nombre)
                    if hijo.get('domain') and hijo_modelo:
                        revisa_dominio(hijo.get('domain'), hijo_modelo, fichero,
                                       hijo.sourceline, 'field (comodel)')
                    elif hijo.get('domain'):
                        revisa_dominio(hijo.get('domain'), modelo, fichero,
                                       hijo.sourceline, 'field')
                    if len(hijo):
                        siguiente = hijo_modelo or modelo
        else:
            if hijo.get('domain'):
                revisa_dominio(hijo.get('domain'), modelo, fichero,
                               hijo.sourceline, hijo.tag)
        # attrs y los modificadores tambien nombran campos del modelo
        for atributo in ('attrs', 'invisible', 'readonly', 'required', 'column_invisible'):
            valor = hijo.get(atributo)
            if valor and valor not in ('1', '0', 'True', 'False') and modelo:
                revisa_dominio(valor, modelo, fichero, hijo.sourceline, atributo)
        recorre(hijo, siguiente, fichero)


total, vistas, sin_modelo = 0, 0, 0
for raiz in MODULOS:
    for carpeta, _subs, ficheros in os.walk(raiz):
        if '__pycache__' in carpeta or '/static/' in carpeta:
            continue
        for fichero in sorted(ficheros):
            if not fichero.endswith('.xml'):
                continue
            ruta = os.path.join(carpeta, fichero)
            corto = ruta.replace('/mnt/extra-addons/', '')
            try:
                arbol = etree.parse(ruta)
            except Exception as e:
                print('NO SE PUDO LEER %s: %s' % (corto, e))
                continue
            total += 1
            for record in arbol.getroot().iter('record'):
                if record.get('model') == 'ir.ui.view':
                    modelo = None
                    arch = None
                    for campo in record.findall('field'):
                        if campo.get('name') == 'model':
                            modelo = (campo.text or '').strip()
                        if campo.get('name') in ('arch', 'arch_db'):
                            arch = campo
                    if arch is None:
                        continue
                    vistas += 1
                    if not modelo:
                        sin_modelo += 1
                        continue
                    if modelo not in MODELOS:
                        continue
                    recorre(arch, modelo, corto)
                elif record.get('model') in ('ir.actions.act_window', 'ir.actions.server'):
                    modelo = None
                    for campo in record.findall('field'):
                        if campo.get('name') == 'res_model':
                            modelo = (campo.text or '').strip()
                    for campo in record.findall('field'):
                        if campo.get('name') == 'domain' and modelo:
                            texto = campo.text or campo.get('eval') or ''
                            revisa_dominio(texto, modelo, corto, campo.sourceline,
                                           'accion')

print('=' * 78)
print('BARRIDO DE VISTAS | %d ficheros xml | %d vistas (%d sin modelo explicito,'
      ' heredadas)' % (total, vistas, sin_modelo))
print('=' * 78)
if not hallazgos:
    print('\n  ningun nombre inexistente')
for (tipo, nombre), sitios in sorted(hallazgos.items()):
    print('\n  %-28s (%s)' % (nombre, tipo))
    for fichero, linea, detalle in sitios[:8]:
        print('        %s:%s   %s' % (fichero, linea, detalle))
env.cr.rollback()
