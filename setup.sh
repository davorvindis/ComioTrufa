#!/bin/bash
# ComioTrufa - Setup script for Raspberry Pi
# Run on fresh Raspberry Pi OS (Bookworm)
set -e

echo "🐕 ComioTrufa - Instalación"
echo "==========================="
echo ""

# Check if running on Raspberry Pi
if [[ ! -f /proc/device-tree/model ]] || ! grep -qi "raspberry" /proc/device-tree/model 2>/dev/null; then
    echo "⚠️  No se detectó Raspberry Pi. Continuando de todos modos..."
fi

# System dependencies
echo "📦 Instalando dependencias del sistema..."
sudo apt update && sudo apt install -y \
    python3-venv python3-pip \
    libcamera-apps python3-libcamera python3-picamera2 \
    sqlite3

# Project directory
PROJECT_DIR="/home/pi/comiotrufa"
if [[ ! -d "$PROJECT_DIR" ]]; then
    echo "📁 Creando directorio del proyecto..."
    mkdir -p "$PROJECT_DIR"
    cp -r . "$PROJECT_DIR/"
fi

cd "$PROJECT_DIR"

# Virtual environment (--system-site-packages for picamera2)
echo "🐍 Creando entorno virtual..."
python3 -m venv venv --system-site-packages
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create directories
mkdir -p images logs

# Environment file
echo ""
echo "🔑 Configuración de credenciales"
echo "---------------------------------"

if [[ ! -f .env ]]; then
    echo ""
    echo "Necesitas:"
    echo "  1. API key de Anthropic (https://console.anthropic.com/)"
    echo "  2. Bot token de Telegram (habla con @BotFather)"
    echo "  3. Tu Chat ID de Telegram (habla con @userinfobot)"
    echo ""

    read -p "API key de Anthropic: " -s ANTHROPIC_API_KEY
    echo ""
    read -p "Token del bot de Telegram: " -s TELEGRAM_BOT_TOKEN
    echo ""
    read -p "Tu Chat ID de Telegram: " TELEGRAM_CHAT_ID

    cat > .env << EOF
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
EOF
    chmod 600 .env
    echo "✅ Credenciales guardadas en .env"
else
    echo "✅ .env ya existe, saltando..."
fi

# Initialize database
echo "💾 Inicializando base de datos..."
source venv/bin/activate
python3 -c "
import sys
sys.path.insert(0, '.')
from comiotrufa.database import Database
db = Database('$PROJECT_DIR/comiotrufa.db')
db.close()
print('  Base de datos creada.')
"

# Install systemd service
echo "⚙️  Instalando servicio systemd..."
sudo cp systemd/comiotrufa.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable comiotrufa

echo ""
echo "✅ ¡Instalación completa!"
echo ""
echo "Comandos útiles:"
echo "  sudo systemctl start comiotrufa    # Iniciar"
echo "  sudo systemctl stop comiotrufa     # Detener"
echo "  sudo systemctl status comiotrufa   # Ver estado"
echo "  sudo journalctl -u comiotrufa -f   # Ver logs en vivo"
echo ""
echo "Para probar manualmente:"
echo "  cd $PROJECT_DIR"
echo "  source venv/bin/activate"
echo "  python -m comiotrufa.main"
echo ""
echo "🐕 ¡Listo! Inicia con: sudo systemctl start comiotrufa"
