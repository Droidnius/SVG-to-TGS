# Bot de Telegram: SVG → TGS

Convierte archivos SVG a `.tgs` (formato de stickers animados de Telegram)
usando la librería `lottie` (que internamente maneja Lottie/Bodymovin y
sabe exportar a TGS, que es un JSON Lottie comprimido con gzip).

## ⚠️ Antes de empezar: qué puedes esperar realmente

- TGS = Lottie comprimido. Lottie es una animación por fotogramas, no un
  formato vectorial estático como SVG.
- Si subes un SVG **estático**, obtendrás un `.tgs` válido pero de **un
  solo fotograma** (no se moverá).
- Si tu SVG tiene animaciones **SMIL o CSS**, `lottie_convert.py` intenta
  interpretarlas, pero el soporte no es perfecto: SVG y Lottie no son
  formatos equivalentes, así que revisa siempre el resultado.
- Para animaciones complejas y confiables, lo normal en la industria es
  crear el diseño directamente en Lottie (After Effects + plugin
  Bodymovin, o en Glaxnimate, que es open source y gratuito).

## Requisitos de Telegram para stickers animados (.tgs)

| Requisito        | Valor           |
|-------------------|-----------------|
| Lienzo             | 512x512 px      |
| Tamaño máximo      | 64 KB           |
| Duración máxima    | 3 segundos      |
| Frame rate         | 60 fps (recomendado) |
| Formato            | Lottie JSON comprimido con gzip |

El bot valida el tamaño automáticamente y te avisa si te pasas del límite.

## 1. Crear el bot en Telegram

1. Abre una conversación con [@BotFather](https://t.me/BotFather).
2. Envía `/newbot` y sigue las instrucciones (nombre y username).
3. BotFather te dará un **token** (algo como `123456:ABC-DEF...`). Guárdalo.

## 2. Preparar el entorno

Necesitas Python 3.10+ y algunas librerías del sistema para renderizar SVG
(usadas por `cairosvg`, que instala `lottie[all]`):

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y libcairo2 libcairo2-dev pkg-config python3-dev

# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias del proyecto
pip install -r requirements.txt
```

Esto instala:
- `python-telegram-bot`: framework para el bot.
- `lottie[all]`: librería de conversión, incluye `lottie_convert.py`
  (herramienta de línea de comandos que el bot usa internamente) y sus
  dependencias opcionales (cairosvg, etc.).

Verifica que la herramienta quedó disponible:

```bash
lottie_convert.py --help
```

## 3. Configurar el token y ejecutar

```bash
export TELEGRAM_BOT_TOKEN="pega_aqui_tu_token"
python bot.py
```

El bot queda escuchando por *polling*. Envíale un `.svg` por chat y te
responderá con el `.tgs` convertido (o con un mensaje de error explicando
por qué no se pudo).

## 4. (Opcional) Convertir el .tgs en un sticker de verdad

Recibir el archivo `.tgs` no lo convierte automáticamente en un sticker
usable. Para eso hay dos caminos:

**A. Manual, con @Stickers:**
1. Habla con [@Stickers](https://t.me/Stickers) en Telegram.
2. `/newanimated` (o `/addsticker` si ya tienes un pack).
3. Sube el `.tgs` que generó tu bot.

**B. Automático, vía API:** desde tu propio bot puedes llamar a
`createNewStickerSet` / `addStickerToSet` del Bot API de Telegram,
pasando el `.tgs` como el sticker. Si quieres, puedo extender `bot.py`
para que haga esto automáticamente tras la conversión — dime a qué
nombre de pack y bajo qué `user_id` quieres publicarlo.

## 5. Desplegar en Fly.io (para que corra 24/7 sin tu máquina)

Este proyecto ya trae `Dockerfile` y `fly.toml` listos para esto. El bot
usa *polling* (se conecta él mismo a Telegram, no expone ningún puerto),
así que en Fly.io se despliega como un proceso "worker" normal — no como
un servicio web — y por eso `fly.toml` **no** tiene sección
`[http_service]`. Fly tiene región en Bogotá (`bog`), la dejé como
`primary_region` para menor latencia.

### Pasos

1. **Instala flyctl** (CLI de Fly.io):
   ```bash
   curl -L https://fly.io/install.sh | sh
   ```
   Luego crea una cuenta / inicia sesión:
   ```bash
   fly auth signup   # o: fly auth login
   ```

2. **Crea la app en Fly** (desde la carpeta del proyecto, donde están
   `Dockerfile` y `fly.toml`):
   ```bash
   fly apps create mi-svg-tgs-bot
   ```
   Usa un nombre único; si el que pusiste en `fly.toml` ya existe, edítalo
   ahí también para que coincida.

3. **Configura el token como secreto** (nunca lo pongas en texto plano en
   el repo ni en `fly.toml`):
   ```bash
   fly secrets set TELEGRAM_BOT_TOKEN="tu_token_de_botfather" --app mi-svg-tgs-bot
   ```

4. **Despliega**:
   ```bash
   fly deploy --app mi-svg-tgs-bot
   ```
   Esto construye la imagen con el `Dockerfile` (incluye `libcairo2`, que
   `lottie[all]` necesita) y arranca la máquina.

5. **Verifica que quedó corriendo**:
   ```bash
   fly status --app mi-svg-tgs-bot
   fly logs --app mi-svg-tgs-bot
   ```
   Deberías ver en los logs la línea `Bot iniciado, esperando mensajes...`.

6. **Prueba desde Telegram**: envíale un `.svg` al bot y confirma que te
   responde con el `.tgs`.

### Notas sobre Fly.io específicas para este tipo de bot

- **No se "duerme" por inactividad HTTP** porque no es un servicio web;
  con `[restart] policy = "always"` en `fly.toml`, si el proceso se cae
  (error no controlado, etc.), Fly lo reinicia solo.
- **Costos**: una VM `shared-cpu-1x` / 512 MB corriendo 24/7 es la carga
  más ligera que ofrece Fly; revisa su página de precios actual antes de
  desplegar, porque puede cambiar.
- **Escalado**: no necesitas más de una máquina para este bot (un solo
  proceso de polling); si corres más de una instancia con el mismo token,
  Telegram vetará las conexiones duplicadas de polling (error 409).
- **Alternativa (Render)**: en Render usarías un "Background Worker" (no
  "Web Service", justamente porque tampoco expone puerto), apuntando el
  *start command* a `python bot.py` y configurando `TELEGRAM_BOT_TOKEN`
  en las variables de entorno del panel. El `Dockerfile` que ya tienes
  también sirve ahí si eliges despliegue por Docker.
- **Logs y monitoreo**: el bot ya loguea con el módulo `logging` de
  Python; en Fly esto queda disponible vía `fly logs`.

## Solución de problemas comunes

- **"lottie_convert.py: command not found"**: asegúrate de tener activado
  el entorno virtual (`source venv/bin/activate`) donde instalaste
  `lottie[all]`.
- **Error relacionado con Cairo**: falta la librería de sistema
  `libcairo2` (ver paso 2).
- **El .tgs pesa más de 64 KB**: simplifica el SVG — menos nodos/paths,
  menos gradientes, convierte texto a formas simples, reduce la
  precisión decimal de las coordenadas.
- **El sticker no se mueve**: tu SVG de origen era estático (ver sección
  de arriba).
