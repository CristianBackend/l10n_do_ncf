# -*- coding: utf-8 -*-
"""Barrido de nombres: comprueba contra el registro REAL de Odoo todos los
nombres de campos y metodos de modelos que usan los dos modulos.

Corre dentro de `odoo shell` sobre una base con los dos modulos instalados, asi
que el registro ya trae los campos propios de los modulos. Revisa:

1. `self.X` dentro de una clase de modelo      -> contra ESE modelo (preciso)
2. `self.env['modelo'].X`                      -> contra ese modelo (preciso)
3. variables locales con modelo conocido:
   `m = self.env['x'].browse(...)` -> `m.X`     -> preciso
4. variable de un bucle sobre un campo o modelo conocido -> preciso
5. `self.campo_relacional.X` (sigue al comodel)          -> preciso
6. `@api.depends/onchange/constrains('a.b')` y `related='a.b'`
7. claves de write()/create({...}), dominios de search(), mapped(), sorted()
8. cualquier otro `algo.X` -> solo avisa si ese nombre no existe en NINGUN
   modelo ni es un atributo normal de Python (orientativo, con ruido)

MODULOS se puede pasar por la variable de entorno BARRIDO_MODULOS (rutas
separadas por comas).
"""
import ast
import io
import os
from collections import defaultdict

env = globals()['env']

MODULOS = [r for r in os.environ.get(
    'BARRIDO_MODULOS',
    '/mnt/extra-addons/l10n_do_ncf,/mnt/extra-addons/l10n_do_ecf_newplain').split(',') if r]

# ----------------------------------------------------------------- registro
MODELOS = {}
TODOS_LOS_NOMBRES = set()
for name in list(env.registry.models):
    try:
        rs = env[name]
    except Exception:
        continue
    MODELOS[name] = set(dir(rs)) | set(rs._fields)
    TODOS_LOS_NOMBRES |= MODELOS[name]


def comodel(modelo, nombre):
    if modelo not in MODELOS:
        return None
    try:
        campo = env[modelo]._fields.get(nombre)
    except Exception:
        return None
    return getattr(campo, 'comodel_name', None) if campo else None


# Atributos normales de Python que aparecen en cualquier codigo.
PY = set()
for tipo in (str, bytes, list, dict, set, tuple, int, float, bool, object,
             Exception, type(None)):
    PY |= set(dir(tipo))
import datetime
import decimal
import logging
import re as _re
for obj in (datetime.datetime, datetime.date, datetime.timedelta, decimal.Decimal,
            logging.getLogger('x'), _re.compile('x')):
    PY |= set(dir(obj))


def literal(nodo):
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, str):
        return nodo.value
    return None


def modelo_de_clase(clase):
    nombres = []
    for cuerpo in clase.body:
        if not isinstance(cuerpo, ast.Assign):
            continue
        for destino in cuerpo.targets:
            if not isinstance(destino, ast.Name) or destino.id not in ('_name', '_inherit'):
                continue
            valor = cuerpo.value
            uno = literal(valor)
            if uno:
                nombres.append((destino.id, uno))
            elif isinstance(valor, (ast.List, ast.Tuple)):
                for elemento in valor.elts:
                    uno = literal(elemento)
                    if uno:
                        nombres.append((destino.id, uno))
    for clave in ('_name', '_inherit'):
        for k, v in nombres:
            if k == clave:
                return v
    return None


def sigue_ruta(modelo, ruta):
    actual = modelo
    for parte in ruta.split('.'):
        if actual is None or actual not in MODELOS:
            return True, None
        if parte not in MODELOS[actual]:
            return False, parte
        actual = comodel(actual, parte)
    return True, None


hallazgos = defaultdict(list)


class Visita(ast.NodeVisitor):
    """Un paso por fichero, llevando el modelo de la clase y de las variables."""

    def __init__(self, fichero):
        self.fichero = fichero
        self.modelo = None
        self.locales = [{}]          # pila de ambitos: variable -> modelo

    # ------------------------------------------------ ambitos
    def ambito(self):
        return self.locales[-1]

    def tipo_de(self, nombre):
        for capa in reversed(self.locales):
            if nombre in capa:
                return capa[nombre]
        return None

    def visit_ClassDef(self, nodo):
        anterior = self.modelo
        modelo = modelo_de_clase(nodo)
        if modelo:
            self.modelo = modelo
        self.locales.append({})
        self.generic_visit(nodo)
        self.locales.pop()
        self.modelo = anterior

    def visit_FunctionDef(self, nodo):
        self.revisa_decoradores(nodo)
        self.locales.append({})
        self.generic_visit(nodo)
        self.locales.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    # ------------------------------------------------ asignaciones y bucles
    def visit_Assign(self, nodo):
        self.generic_visit(nodo)
        modelo = self.modelo_de_expresion(nodo.value)
        for destino in nodo.targets:
            if isinstance(destino, ast.Name):
                if modelo:
                    self.ambito()[destino.id] = modelo
                else:
                    self.ambito().pop(destino.id, None)

    def visit_For(self, nodo):
        iterado = self.modelo_de_expresion(nodo.iter)
        if isinstance(nodo.target, ast.Name) and iterado:
            self.ambito()[nodo.target.id] = iterado
        self.generic_visit(nodo)

    # ------------------------------------------------ atributos
    def visit_Attribute(self, nodo):
        objetivo = self.modelo_de_expresion(nodo.value)
        if objetivo and objetivo in MODELOS:
            if nodo.attr not in MODELOS[objetivo]:
                hallazgos[('campo o metodo', nodo.attr)].append(
                    (self.fichero, nodo.lineno, objetivo))
        elif objetivo is None:
            if (nodo.attr not in TODOS_LOS_NOMBRES and nodo.attr not in PY
                    and not nodo.attr.startswith('__')):
                hallazgos[('nombre desconocido', nodo.attr)].append(
                    (self.fichero, nodo.lineno, '?'))
        self.generic_visit(nodo)

    # ------------------------------------------------ de que modelo es algo
    MISMO_MODELO = {
        'browse', 'search', 'create', 'sudo', 'with_context', 'with_company',
        'with_user', 'with_env', 'filtered', 'filtered_domain', 'sorted',
        'exists', 'union', 'ensure_one', 'copy', 'new', 'with_prefetch',
    }

    def modelo_de_expresion(self, nodo):
        if isinstance(nodo, ast.Name):
            if nodo.id == 'self':
                return self.modelo
            return self.tipo_de(nodo.id)
        if isinstance(nodo, ast.Subscript):
            valor = nodo.value
            es_env = (isinstance(valor, ast.Name) and valor.id == 'env') or (
                isinstance(valor, ast.Attribute) and valor.attr == 'env')
            if es_env:
                return literal(nodo.slice)
            # m[:1] / m[0] siguen siendo del mismo modelo
            return self.modelo_de_expresion(valor)
        if isinstance(nodo, ast.Call):
            if isinstance(nodo.func, ast.Attribute):
                if nodo.func.attr in self.MISMO_MODELO:
                    return self.modelo_de_expresion(nodo.func.value)
                if nodo.func.attr == 'mapped' and nodo.args:
                    ruta = literal(nodo.args[0])
                    base = self.modelo_de_expresion(nodo.func.value)
                    if ruta and base:
                        actual = base
                        for parte in ruta.split('.'):
                            actual = comodel(actual, parte)
                            if actual is None:
                                return None
                        return actual
            return None
        if isinstance(nodo, ast.Attribute):
            padre = self.modelo_de_expresion(nodo.value)
            if padre:
                return comodel(padre, nodo.attr)
            return None
        return None

    # ------------------------------------------------ cadenas con nombres
    def revisa_decoradores(self, nodo):
        for deco in nodo.decorator_list:
            if (isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in ('depends', 'onchange', 'constrains')):
                for arg in deco.args:
                    ruta = literal(arg)
                    if ruta and self.modelo:
                        ok, falla = sigue_ruta(self.modelo, ruta)
                        if not ok:
                            hallazgos[('@api.%s' % deco.func.attr, falla)].append(
                                (self.fichero, deco.lineno,
                                 '%s -> %s' % (self.modelo, ruta)))

    def visit_Call(self, nodo):
        for kw in nodo.keywords or []:
            ruta = literal(kw.value)
            if not ruta or not self.modelo:
                continue
            if kw.arg == 'related':
                ok, falla = sigue_ruta(self.modelo, ruta)
                if not ok:
                    hallazgos[('related', falla)].append(
                        (self.fichero, nodo.lineno, '%s -> %s' % (self.modelo, ruta)))
            elif kw.arg in ('compute', 'inverse', 'search', 'currency_field'):
                if self.modelo in MODELOS and ruta not in MODELOS[self.modelo]:
                    hallazgos[('%s= del campo' % kw.arg, ruta)].append(
                        (self.fichero, nodo.lineno, self.modelo))

        if isinstance(nodo.func, ast.Attribute):
            metodo = nodo.func.attr
            destino = self.modelo_de_expresion(nodo.func.value)
            if metodo in ('mapped', 'sorted', 'read_group') and nodo.args and destino:
                ruta = literal(nodo.args[0])
                if ruta:
                    ok, falla = sigue_ruta(destino, ruta)
                    if not ok:
                        hallazgos[(metodo, falla)].append(
                            (self.fichero, nodo.lineno, '%s -> %s' % (destino, ruta)))
            if metodo in ('write', 'create', 'update') and nodo.args and destino:
                arg = nodo.args[0]
                dicts = [arg] if isinstance(arg, ast.Dict) else (
                    [e for e in arg.elts if isinstance(e, ast.Dict)]
                    if isinstance(arg, (ast.List, ast.Tuple)) else [])
                for d in dicts:
                    for clave in d.keys:
                        nombre = literal(clave)
                        if nombre and destino in MODELOS and nombre not in MODELOS[destino]:
                            hallazgos[('clave de %s' % metodo, nombre)].append(
                                (self.fichero, nodo.lineno, destino))
            if metodo in ('search', 'search_count', 'search_read', 'filtered_domain',
                          '_search') and nodo.args and destino:
                self.revisa_dominio(nodo.args[0], destino, nodo.lineno)
        self.generic_visit(nodo)

    def revisa_dominio(self, nodo, modelo, linea):
        if not isinstance(nodo, (ast.List, ast.Tuple)):
            return
        for elemento in nodo.elts:
            if isinstance(elemento, (ast.Tuple, ast.List)) and elemento.elts:
                campo = literal(elemento.elts[0])
                if not campo:
                    continue
                ok, falla = sigue_ruta(modelo, campo)
                if not ok:
                    hallazgos[('dominio', falla)].append(
                        (self.fichero, linea, '%s -> %s' % (modelo, campo)))


total = 0
for raiz in MODULOS:
    for carpeta, _subs, ficheros in os.walk(raiz):
        if '__pycache__' in carpeta or carpeta.endswith('/tests'):
            continue
        for fichero in sorted(ficheros):
            if not fichero.endswith('.py'):
                continue
            ruta = os.path.join(carpeta, fichero)
            try:
                arbol = ast.parse(io.open(ruta, encoding='utf-8-sig').read())
            except Exception as e:
                print('NO SE PUDO LEER %s: %s' % (ruta, e))
                continue
            total += 1
            Visita(ruta.replace('/mnt/extra-addons/', '').replace(
                '/mnt/revision/', '')).visit(arbol)

import odoo.release
print('=' * 78)
print('BARRIDO contra el registro de Odoo %s | %d ficheros | %d modelos'
      % ('.'.join(str(x) for x in odoo.release.version_info[:2]), total, len(MODELOS)))
print('rutas: %s' % ', '.join(MODULOS))
print('=' * 78)

precisos = {k: v for k, v in hallazgos.items() if k[0] != 'nombre desconocido'}
vagos = sorted({k[1] for k, v in hallazgos.items() if k[0] == 'nombre desconocido'})

print('\n--- NO EXISTEN EN ODOO (resuelto contra un modelo concreto) ---')
if not precisos:
    print('  ninguno')
for (tipo, nombre), sitios in sorted(precisos.items()):
    print('  %-30s %-24s en %s' % (nombre, '(%s)' % tipo, sitios[0][2]))
    for fichero, linea, _d in sitios[:8]:
        print('        %s:%s' % (fichero, linea))

print('\n--- receptor no resuelto, y el nombre no esta en ningun modelo (%d) ---'
      % len(vagos))
print('   ' + ', '.join(vagos))
env.cr.rollback()
