# Liga de hándicap — RFEGolf

Tabla de hándicap de un grupo de amigos que se actualiza sola una vez a la
semana, leyendo la web de la RFEG y mostrando flechas de tendencia (▲/▼/=)
según quién ha adelantado o ha sido adelantado en el ranking.

## Cómo funciona

1. **`scraper.py`** consulta `rfegolf.es` para cada persona de `friends.json`
   y extrae nombre, licencia, hándicap, estado y última modificación.
2. **`.github/workflows/update.yml`** ejecuta ese script automáticamente
   todos los lunes (y también se puede lanzar a mano), y guarda el
   resultado en `data/latest.json` y `data/history.json`.
3. **`index.html`** es la página que ves tú: lee `data/latest.json`
   directamente desde GitHub (vía `raw.githubusercontent.com`, que sí
   permite cargarlo desde un navegador) y pinta la tabla con las flechas.

## Puesta en marcha (10 minutos)

1. **Crea un repositorio en GitHub** (público; si fuera privado
   `raw.githubusercontent.com` no serviría el JSON sin autenticación).
   Puede llamarse, por ejemplo, `handicap-amigos`.

2. **Sube estos archivos** tal cual están (mantén la carpeta `.github/`).

3. **Edita `friends.json`** y añade a todo el grupo (10-20 personas). Cada
   entrada necesita el nombre y apellidos exactamente como en la web de la
   RFEG, y la licencia (para evitar confundir a dos personas con el mismo
   nombre):

   ```json
   [
     {
       "id": "ignacio",
       "nombre": "Ignacio",
       "apellido1": "Zaballos",
       "apellido2": "Palop",
       "licencia_esperada": "LV17911563"
     },
     {
       "id": "otro_amigo",
       "nombre": "...",
       "apellido1": "...",
       "apellido2": "...",
       "licencia_esperada": "..."
     }
   ]
   ```

4. **Lanza el Action una primera vez a mano**: en GitHub, pestaña
   *Actions* → *Actualizar hándicaps* → *Run workflow*. Esto genera el
   primer `data/latest.json`.

5. **Edita `index.html`** y cambia esta línea por la de tu repositorio:

   ```js
   DATA_URL: "https://raw.githubusercontent.com/TU-USUARIO/TU-REPO/main/data/latest.json",
   ```

   (y `YOU_ID` si quieres que tu propia fila se resalte).

6. **Abre `index.html`** — puedes abrirlo directamente en el navegador,
   subirlo a GitHub Pages, o pegarlo como artifact en Claude para verlo
   dentro del chat. En cualquiera de los tres casos leerá siempre los
   datos más recientes de tu repositorio.

A partir de aquí, cada lunes el Action vuelve a consultar la RFEG, guarda
el nuevo snapshot y calcula automáticamente quién ha subido, bajado o
mantenido su puesto respecto a la semana anterior.

## Notas

- El **hándicap más bajo es el mejor puntuado** (así funciona el sistema
  RFEG), por lo que el ranking se ordena de menor a mayor hándicap.
- Si la web de la RFEG cambia de estructura o alguien no aparece,
  `scraper.py` no rompe el resto: marca solo a esa persona con un error
  y mantiene los datos de la semana anterior en el histórico.
- El histórico completo se guarda en `data/history.json`, así que en el
  futuro se puede añadir fácilmente una gráfica de evolución del
  hándicap de cada uno, no solo el ranking de la semana.
- Puedes cambiar el día/hora de actualización editando la línea `cron`
  en `.github/workflows/update.yml` (está en hora UTC).
