/**
 * ComioTrufa - ESP32-CAM Firmware
 *
 * Saca una foto cada N minutos y la envía por HTTP POST
 * a un servidor Python que hace el procesamiento con IA.
 *
 * Hardware: ESP32-CAM con OV2640
 *
 * Configuración:
 *   1. Instalar en Arduino IDE: ESP32 board support
 *   2. Board: "AI Thinker ESP32-CAM"
 *   3. Configurar WiFi y SERVER_URL abajo
 *   4. Upload con el programador ESP32-CAM-MB
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include "esp_timer.h"
#include "esp_sleep.h"

// ============ CONFIGURACIÓN - EDITAR AQUÍ ============

// WiFi
const char* WIFI_SSID = "Personal-MD-2.4";
const char* WIFI_PASSWORD = "TRUFA401";

// Servidor (tu PC o servidor en la nube)
const char* SERVER_URL = "https://comiotrufa.onrender.com/api/photo";
const char* CHECK_URL = "https://comiotrufa.onrender.com/api/should-capture";

// Intervalo entre fotos (en minutos)
const int INTERVAL_MINUTES = 5;

// Calidad de imagen JPEG (10-63, menor = mejor calidad pero más grande)
const int JPEG_QUALITY = 12;

// Resolución de la cámara
// FRAMESIZE_QVGA   = 320x240
// FRAMESIZE_VGA    = 640x480
// FRAMESIZE_SVGA   = 800x600
// FRAMESIZE_XGA    = 1024x768
// FRAMESIZE_SXGA   = 1280x1024
// FRAMESIZE_UXGA   = 1600x1200
const int FRAME_SIZE = FRAMESIZE_SVGA;  // 800x600 - buen balance

// ============ FIN CONFIGURACIÓN ============

// Pin definitions for AI-Thinker ESP32-CAM
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// LED flash
#define FLASH_LED_PIN      4

// Watchdog timer (reinicia si se cuelga)
#define WDT_TIMEOUT_S     60

int failCount = 0;
const int MAX_FAILURES = 10;  // Reiniciar después de 10 fallos consecutivos

void setup() {
  Serial.begin(115200);
  Serial.println("\n\n=== ComioTrufa ESP32-CAM ===");

  // Desactivar flash LED
  pinMode(FLASH_LED_PIN, OUTPUT);
  digitalWrite(FLASH_LED_PIN, LOW);

  // Inicializar cámara
  if (!initCamera()) {
    Serial.println("ERROR: No se pudo inicializar la cámara. Reiniciando...");
    delay(3000);
    ESP.restart();
  }

  // Conectar WiFi
  connectWiFi();

  // Configurar hora Argentina (UTC-3)
  configTime(-3 * 3600, 0, "pool.ntp.org", "time.nist.gov");
  Serial.print("Sincronizando hora...");
  struct tm timeinfo;
  int retries = 0;
  while (!getLocalTime(&timeinfo) && retries < 10) {
    delay(500);
    Serial.print(".");
    retries++;
  }
  if (retries < 10) {
    Serial.printf(" OK: %02d:%02d:%02d\n", timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
  } else {
    Serial.println(" WARN: no se pudo sincronizar hora");
  }

  Serial.printf("Intervalo: %d minutos\n", INTERVAL_MINUTES);
  Serial.println("Horario activo: 7:00 - 1:00 (duerme 1:00-7:00)");
  Serial.println("Setup completo. Iniciando monitoreo...\n");
}

void loop() {
  // Verificar WiFi
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi desconectado. Reconectando...");
    connectWiFi();
  }

  // Chequear si estamos en horario nocturno (1:00 - 7:00 = no capturar)
  struct tm timeinfo;
  if (getLocalTime(&timeinfo)) {
    int hour = timeinfo.tm_hour;
    if (hour >= 1 && hour < 7) {
      Serial.printf("Horario nocturno (%02d:%02d), saltando...\n", hour, timeinfo.tm_min);
      delay(INTERVAL_MINUTES * 60 * 1000UL);
      return;
    }
  }

  // Capturar y enviar foto
  bool success = captureAndSend();

  if (success) {
    failCount = 0;
    Serial.println("OK - Foto enviada correctamente\n");
  } else {
    failCount++;
    Serial.printf("ERROR - Fallo #%d/%d\n\n", failCount, MAX_FAILURES);

    if (failCount >= MAX_FAILURES) {
      Serial.println("Demasiados fallos. Reiniciando...");
      delay(1000);
      ESP.restart();
    }
  }

  // Esperar hasta la próxima captura, pero chequear pedidos cada 10 seg
  Serial.printf("Esperando %d minutos (chequeando pedidos cada 10s)...\n", INTERVAL_MINUTES);

  unsigned long waitMs = INTERVAL_MINUTES * 60 * 1000UL;
  unsigned long start = millis();
  while (millis() - start < waitMs) {
    delay(10000);  // Chequear cada 10 segundos
    if (checkPhotoRequest()) {
      Serial.println("Foto pedida desde el front!");
      captureAndSend();
    }
  }
}

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;
  config.fb_location = CAMERA_FB_IN_PSRAM;

  // Calidad y tamaño
  config.frame_size = (framesize_t)FRAME_SIZE;
  config.jpeg_quality = JPEG_QUALITY;
  config.fb_count = 1;

  // Si hay PSRAM, usar mejor calidad
  if (psramFound()) {
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
    Serial.println("PSRAM encontrada - usando doble buffer");
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Error inicializando cámara: 0x%x\n", err);
    return false;
  }

  // Ajustes de imagen
  sensor_t *s = esp_camera_sensor_get();
  s->set_brightness(s, 1);     // Brillo +1
  s->set_contrast(s, 1);       // Contraste +1
  s->set_saturation(s, 0);     // Saturación normal
  s->set_whitebal(s, 1);       // Auto white balance ON
  s->set_awb_gain(s, 1);       // AWB gain ON
  s->set_exposure_ctrl(s, 1);  // Auto exposure ON

  Serial.println("Cámara inicializada correctamente");
  return true;
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.printf("Conectando a WiFi '%s'", WIFI_SSID);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nConectado! IP: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("Señal WiFi: %d dBm\n", WiFi.RSSI());
  } else {
    Serial.println("\nERROR: No se pudo conectar a WiFi");
    Serial.println("Reiniciando en 10 segundos...");
    delay(10000);
    ESP.restart();
  }
}

bool checkPhotoRequest() {
  if (WiFi.status() != WL_CONNECTED) return false;

  WiFiClientSecure client;
  client.setInsecure();  // Skip cert verification (ok for this use case)
  HTTPClient http;
  http.begin(client, CHECK_URL);
  http.setTimeout(5000);
  int httpCode = http.GET();

  if (httpCode == 200) {
    String response = http.getString();
    http.end();
    return response.indexOf("true") > 0;
  }

  http.end();
  return false;
}

bool captureAndSend() {
  Serial.println("Capturando foto...");

  // Encender flash LED para iluminar el plato
  digitalWrite(FLASH_LED_PIN, HIGH);
  delay(500);  // Dar tiempo a la cámara para ajustar exposición

  // Descartar frames viejos para que el sensor se adapte a la luz
  camera_fb_t *fb = esp_camera_fb_get();
  if (fb) { esp_camera_fb_return(fb); delay(300); }
  fb = esp_camera_fb_get();
  if (fb) { esp_camera_fb_return(fb); delay(300); }

  // Capturar frame bueno (con flash encendido)
  fb = esp_camera_fb_get();

  // Apagar flash
  digitalWrite(FLASH_LED_PIN, LOW);

  if (!fb) {
    Serial.println("ERROR: No se pudo capturar la foto");
    return false;
  }

  Serial.printf("Foto capturada: %u bytes (%dx%d)\n", fb->len, fb->width, fb->height);

  // Enviar por HTTPS
  bool result = sendPhoto(fb->buf, fb->len);

  esp_camera_fb_return(fb);
  return result;
}

bool sendPhoto(uint8_t *imageData, size_t imageLen) {
  WiFiClientSecure client;
  client.setInsecure();  // Skip cert verification
  HTTPClient http;

  Serial.printf("Enviando a %s ...\n", SERVER_URL);

  http.begin(client, SERVER_URL);
  http.setTimeout(30000);  // 30 segundos timeout
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("X-Device-ID", "comiotrufa-esp32");

  int httpCode = http.POST(imageData, imageLen);

  if (httpCode > 0) {
    String response = http.getString();
    Serial.printf("HTTP %d: %s\n", httpCode, response.c_str());
    http.end();
    return (httpCode == 200);
  } else {
    Serial.printf("HTTP error: %s\n", http.errorToString(httpCode).c_str());
    http.end();
    return false;
  }
}
