# Barridos de nombres contra el registro de Odoo

Dos guiones para comprobar que **todos los nombres de campos y métodos de
modelos que usa el código existen en la versión de Odoo con la que va a
correr**. Se escribieron para el porte de la 19 a la 16, donde un nombre que
desapareció entre versiones no da ningún error hasta que alguien pasa por esa
línea; sirven igual para cualquier porte o actualización.

Los dos corren dentro de `odoo shell`, sobre una base con los módulos
instalados: así el registro es el de verdad y ya trae los campos propios de los
módulos, sin tener que interpretar el código fuente de Odoo.

## Cómo se corren

```bash
# los módulos montados en /mnt/extra-addons y la base con los dos instalados
docker run --rm --network <red> -e HOST=<pg> -e USER=odoo -e PASSWORD=odoo \
  -v <addons>:/mnt/extra-addons:ro -i odoo:16 \
  odoo shell -d <base> --no-http --max-cron-threads=0 \
  --addons-path=/usr/lib/python3/dist-packages/odoo/addons,/mnt/extra-addons \
  < tools/barrido_nombres.py
```

Lo mismo con `tools/barrido_vistas.py`. Para barrer otras rutas (por ejemplo
una revisión antigua exportada aparte, para comprobar que el barrido detecta un
fallo conocido):

```bash
  -e BARRIDO_MODULOS=/mnt/revision/l10n_do_ncf
```

## Qué revisa cada uno

**`barrido_nombres.py`** — el código Python:

| Resuelto con precisión | Cómo |
| --- | --- |
| `self.X` en una clase de modelo | contra ese modelo (`_name` / `_inherit`) |
| `self.env['modelo'].X` | contra ese modelo |
| `m = self.env['x'].browse(...)` → `m.X` | sigue la variable local |
| `for linea in self.line_ids:` → `linea.X` | sigue la variable del bucle |
| `self.partner_id.X` | salta al comodel del campo |
| `@api.depends/onchange/constrains('a.b')`, `related=`, `compute=` | recorre la ruta |
| claves de `write()`/`create()`, dominios de `search()`, `mapped()`, `sorted()` | contra el modelo del receptor |

**`barrido_vistas.py`** — los XML: cada `<field name="X">` contra el modelo de
la vista (entrando al comodel en las subvistas de un one2many), y los `domain=`,
`attrs` y modificadores. Odoo ya valida al instalar que los campos de una vista
existan —un nombre mal escrito da `ParseError`—, pero **los dominios de las
vistas no**: se evalúan en el navegador, así que un nombre mal escrito no da
error, simplemente no filtra nunca. Eso es lo que aporta este guion.

## Cómo se lee la salida

- **`NO EXISTEN EN ODOO`**: lo que hay que mirar. Son nombres resueltos contra
  un modelo concreto, con fichero y línea.
- **`receptor no resuelto, y el nombre no está en ningún modelo`**: orientativo
  y con ruido. Ahí caen los atributos de objetos que no son registros
  (`fields.Char`, `tools.float_round`, `requests.exceptions`,
  `api.model_create_multi`...). Se repasa a ojo: si alguno fuese un campo de
  modelo, es un fallo.

## Comprobar que el barrido sirve

Antes de fiarse de un "ninguno", conviene correrlo sobre una revisión con un
fallo **conocido**. En el porte a la 16 se hizo así: se exportó el código
anterior al arreglo de `invoice_currency_rate` (un campo del núcleo que llegó en
Odoo 17 y que la 16 no tiene) y el barrido lo señaló en su línea exacta, junto a
un segundo nombre inexistente que nadie había visto (`final_number`, que hacía
que publicar un B12 se cayera).
