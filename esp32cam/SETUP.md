# ESP32-CAM - Guía de Setup

## Hardware necesario

- ESP32-CAM con OV2640 + placa programador (ESP32-CAM-MB)
- Cable USB Micro-B (para programar y alimentar)
- Cargador USB 5V cualquiera (para alimentación permanente)

## Instalación del Arduino IDE

### 1. Instalar Arduino IDE
Descargar de: https://www.arduino.cc/en/software

### 2. Agregar soporte ESP32
1. Abrir Arduino IDE
2. Ir a **File → Preferences**
3. En "Additional Board Manager URLs" agregar:
   ```
   https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
   ```
4. Ir a **Tools → Board → Board Manager**
5. Buscar "esp32" e instalar **esp32 by Espressif Systems**

### 3. Seleccionar la placa
1. **Tools → Board → ESP32 Arduino → AI Thinker ESP32-CAM**
2. **Tools → Port** → Seleccionar el puerto COM/USB del programador

## Configurar el código

Abrir `esp32cam.ino` y editar las 3 líneas de configuración:

```cpp
const char* WIFI_SSID = "TU_WIFI_NOMBRE";      // Nombre de tu WiFi
const char* WIFI_PASSWORD = "TU_WIFI_CLAVE";    // Contraseña de tu WiFi
const char* SERVER_URL = "http://192.168.1.100:8000/api/photo";  // IP de tu servidor
```

### ¿Cómo saber la IP del servidor?
- **Si el servidor corre en tu PC**: Abrí una terminal y ejecutá `ipconfig` (Windows) o `ifconfig` / `ip a` (Mac/Linux). Buscá la IP local (empieza con 192.168...)
- **Si usás servidor en la nube**: Usá la URL del servidor desplegado (ej: `https://comiotrufa.onrender.com/api/photo`)

## Subir el código

1. Conectar la ESP32-CAM al programador (ESP32-CAM-MB)
2. Conectar el USB a tu computadora
3. En Arduino IDE: **Sketch → Upload** (o Ctrl+U)
4. Esperar a que diga "Done uploading"
5. Abrir **Tools → Serial Monitor** (115200 baud) para ver los logs

## Verificar que funciona

En el Serial Monitor deberías ver:
```
=== ComioTrufa ESP32-CAM ===
PSRAM encontrada - usando doble buffer
Cámara inicializada correctamente
Conectando a WiFi 'TuRed'...
Conectado! IP: 192.168.1.50
Señal WiFi: -45 dBm
Intervalo: 5 minutos
Setup completo. Iniciando monitoreo...

Capturando foto...
Foto capturada: 35420 bytes (800x600)
Enviando a http://192.168.1.100:8000/api/photo ...
HTTP 200: {"status":"ok","state":"food","confidence":0.95}
OK - Foto enviada correctamente
```

## Montaje

1. Limpiar la superficie donde vas a pegar con alcohol
2. Pegar cinta 3M VHB al case/carcasa de la ESP32-CAM
3. Posicionar a 40-60cm arriba del plato, mirando hacia abajo
4. Conectar el USB a un cargador y enchufar

## Troubleshooting

| Problema | Solución |
|----------|----------|
| "No se pudo inicializar la cámara" | Revisar que la cámara está bien conectada al conector (el cable dorado). Presionar suavemente. |
| "No se pudo conectar a WiFi" | Verificar SSID y password. La ESP32-CAM solo soporta WiFi 2.4GHz (no 5GHz). |
| "HTTP error" | Verificar que el servidor está corriendo y la IP es correcta. Probar acceder a `http://IP:8000/health` desde el navegador. |
| Se reinicia constantemente | Probablemente la fuente USB no da suficiente corriente. Probar con otro cargador (mínimo 1A). |
