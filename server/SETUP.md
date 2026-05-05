# Servidor ComioTrufa - Guía de Setup

## Opción A: Correr en tu computadora (más fácil)

### Requisitos
- Python 3.10+
- Tu compu conectada al mismo WiFi que la ESP32-CAM

### Instalación

```bash
cd ComioTrufa

# Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate   # Linux/Mac
# .venv\Scripts\activate    # Windows

# Instalar dependencias
pip install -r requirements.txt

# Configurar credenciales
cp .env.example .env
# Editar .env con tus keys
```

### Configurar .env

```bash
ANTHROPIC_API_KEY=sk-ant-api03-...    # De https://console.anthropic.com/
TELEGRAM_BOT_TOKEN=123456:ABC...       # De @BotFather en Telegram
TELEGRAM_CHAT_ID=123456789             # De @userinfobot en Telegram
```

### Ejecutar

```bash
# Cargar variables de entorno
export $(cat .env | xargs)   # Linux/Mac
# En Windows: setear manualmente o usar python-dotenv

# Iniciar servidor
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

El servidor ahora escucha en `http://TU_IP:8000/api/photo`

### Verificar

Abrir en el navegador: `http://localhost:8000/health`
Debería responder: `{"status":"healthy"}`

---

## Opción B: Deploy en la nube (gratis, siempre encendido)

### Render.com (recomendado, gratis)

1. Crear cuenta en https://render.com
2. Crear "New Web Service"
3. Conectar con tu repo de GitHub
4. Configurar:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn server.app:app --host 0.0.0.0 --port $PORT`
5. Agregar Environment Variables:
   - `ANTHROPIC_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
6. Deploy!

Tu URL será algo como: `https://comiotrufa-xxxx.onrender.com`
Configurar esa URL en el `esp32cam.ino` como `SERVER_URL`.

### Railway.app (alternativa)

Similar a Render. Tiene free tier para proyectos pequeños.

---

## Cómo crear el Bot de Telegram

1. Abrir Telegram y buscar **@BotFather**
2. Enviar `/newbot`
3. Elegir un nombre (ej: "ComioTrufa Bot")
4. Elegir un username (ej: "comiotrufa_bot")
5. BotFather te da el **token** → guardarlo en `.env`

## Cómo obtener tu Chat ID

1. Abrir Telegram y buscar **@userinfobot**
2. Enviar `/start`
3. Te responde con tu **ID** (número) → guardarlo en `.env`

---

## Endpoints del servidor

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/photo` | POST | Recibe foto JPEG de la ESP32 |
| `/api/status` | GET | Estado actual del plato |
| `/health` | GET | Health check |
