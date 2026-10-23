/*
 * ESP32-S3 USB Host UVC Webcam -> Wi-Fi MJPEG stream
 * ---------------------------------------------------------------------
 * Connects a UVC-class USB webcam (e.g. a Logitech webcam) to the
 * ESP32-S3's native USB-OTG port in HOST mode, pulls MJPEG frames from
 * it via Espressif's usb_stream component, and re-serves those frames
 * over Wi-Fi as an MJPEG stream - same idea as the camera-module sketch,
 * but the video source is now a USB webcam instead of esp_camera.
 *
 * You can point esp32_aruco_stream.py / debug_aruco.py at this exactly
 * the same way, just with a different port/path if you change it below.
 *
 * IMPORTANT - things you will likely need to tune once you can test on
 * real hardware (I can't run this myself, so treat this as a strong
 * starting point rather than guaranteed-correct):
 *   - Your Logitech webcam's supported USB UVC frame sizes/formats.
 *     FRAME_RESOLUTION_ANY lets usb_stream auto-negotiate, but if the
 *     webcam doesn't offer MJPEG mode at all (rare, but some cheap/older
 *     webcams are YUYV-only), this will need YUV->JPEG conversion added.
 *   - USB power: many webcams draw more current than the ESP32-S3's
 *     OTG port alone can supply - you likely need a powered USB hub or
 *     external 5V injection.
 *   - Buffer sizes (xfer/frame buffer) below are reasonable starting
 *     points but may need adjusting for your webcam's max frame size.
 *
 * Build/flash with VS Code's ESP-IDF extension, target esp32s3.
 */

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_err.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_http_server.h"
#include "nvs_flash.h"
#include "usb_stream.h"

static const char *TAG = "web_cam";

// ---------------------------------------------------------------------
// Fill in your Wi-Fi credentials
// ---------------------------------------------------------------------
#define WIFI_SSID     "Jialo.mi"
#define WIFI_PASSWORD "fml121202"

// ---------------------------------------------------------------------
// Fixed IP on the hotspot, so the stream URL never changes. These suit an
// iPhone hotspot (172.20.10.0/28, gateway .1, clients .2-.14); .5 is the address
// the hotspot gave this board before, so existing scripts keep working.
// Comment out USE_STATIC_IP to go back to DHCP.
// ---------------------------------------------------------------------
#define USE_STATIC_IP
#define STATIC_IP      ESP_IP4TOADDR(172, 20, 10, 5)
#define STATIC_GW      ESP_IP4TOADDR(172, 20, 10, 1)
#define STATIC_NETMASK ESP_IP4TOADDR(255, 255, 255, 240)

// ---------------------------------------------------------------------
// Latest-frame buffer shared between the UVC callback (producer) and the
// HTTP handlers (consumers). Protected by a mutex since they run on
// different tasks/contexts.
// ---------------------------------------------------------------------
#define MAX_JPEG_FRAME_SIZE (60 * 1024)

static SemaphoreHandle_t frame_mutex;
static uint8_t *latest_frame_buf = NULL;   // holds a copy of the newest JPEG
static size_t latest_frame_len = 0;
static volatile bool have_frame = false;

// Buffers required by usb_stream itself (separate from the "latest frame"
// copy above). Allocated from PSRAM since they're sizable.
#define XFER_BUFFER_SIZE (32 * 1024)
#define FRAME_BUFFER_SIZE (60 * 1024)
static uint8_t *xfer_buffer_a = NULL;
static uint8_t *xfer_buffer_b = NULL;
static uint8_t *uvc_frame_buffer = NULL;

// ---------------------------------------------------------------------
// Called by usb_stream on every completed UVC frame. Runs in a USB task
// context - keep it fast, just copy the JPEG bytes out.
// ---------------------------------------------------------------------
static void camera_frame_cb(uvc_frame_t *frame, void *user_ptr)
{
    if (frame->frame_format != UVC_FRAME_FORMAT_MJPEG) {
        // Only handling MJPEG in this starting version. If your webcam
        // only offers YUYV, you'd add a JPEG encode step here.
        return;
    }
    if (frame->data_bytes == 0 || frame->data_bytes > MAX_JPEG_FRAME_SIZE) {
        ESP_LOGW(TAG, "Dropping frame of size %u (too large or empty)", (unsigned)frame->data_bytes);
        return;
    }

    if (xSemaphoreTake(frame_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
        memcpy(latest_frame_buf, frame->data, frame->data_bytes);
        latest_frame_len = frame->data_bytes;
        have_frame = true;
        xSemaphoreGive(frame_mutex);
    }
}

// ---------------------------------------------------------------------
// Wi-Fi station setup (blocks until connected)
// ---------------------------------------------------------------------
static EventGroupHandle_t wifi_event_group;
#define WIFI_CONNECTED_BIT BIT0

static esp_netif_t *sta_netif = NULL;

#ifdef USE_STATIC_IP
// Same approach as ESP-IDF's static_ip example: stop the DHCP client and
// set the address once associated; esp_netif then posts IP_EVENT_STA_GOT_IP.
static void set_static_ip(esp_netif_t *netif)
{
    esp_err_t err = esp_netif_dhcpc_stop(netif);
    if (err != ESP_OK && err != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED) {
        ESP_LOGE(TAG, "Failed to stop DHCP client: %s", esp_err_to_name(err));
        return;
    }
    esp_netif_ip_info_t ip = {
        .ip = { .addr = STATIC_IP },
        .gw = { .addr = STATIC_GW },
        .netmask = { .addr = STATIC_NETMASK },
    };
    ESP_ERROR_CHECK(esp_netif_set_ip_info(netif, &ip));
}
#endif

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                                int32_t event_id, void *event_data)
{
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
#ifdef USE_STATIC_IP
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_CONNECTED) {
        set_static_ip(sta_netif);
#endif
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        ESP_LOGW(TAG, "Wi-Fi disconnected, retrying...");
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

static void wifi_init_sta(void)
{
    wifi_event_group = xEventGroupCreate();

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    sta_netif = esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));

    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASSWORD,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    ESP_LOGI(TAG, "Connecting to Wi-Fi SSID: %s", WIFI_SSID);
    xEventGroupWaitBits(wifi_event_group, WIFI_CONNECTED_BIT, pdFALSE, pdTRUE, portMAX_DELAY);
}

// ---------------------------------------------------------------------
// HTTP: single-frame snapshot at /capture
// ---------------------------------------------------------------------
static esp_err_t capture_handler(httpd_req_t *req)
{
    if (!have_frame) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "No frame yet");
        return ESP_FAIL;
    }

    esp_err_t res = ESP_OK;
    if (xSemaphoreTake(frame_mutex, pdMS_TO_TICKS(200)) == pdTRUE) {
        httpd_resp_set_type(req, "image/jpeg");
        res = httpd_resp_send(req, (const char *)latest_frame_buf, latest_frame_len);
        xSemaphoreGive(frame_mutex);
    } else {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "Busy");
        res = ESP_FAIL;
    }
    return res;
}

// ---------------------------------------------------------------------
// HTTP: MJPEG stream at /stream (same multipart format as the camera
// module version, so your Python scripts work unchanged)
// ---------------------------------------------------------------------
#define PART_BOUNDARY "123456789000000000000987654321"
static const char *STREAM_CONTENT_TYPE = "multipart/x-mixed-replace;boundary=" PART_BOUNDARY;
static const char *STREAM_BOUNDARY = "\r\n--" PART_BOUNDARY "\r\n";
static const char *STREAM_PART = "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

static esp_err_t stream_handler(httpd_req_t *req)
{
    esp_err_t res = httpd_resp_set_type(req, STREAM_CONTENT_TYPE);
    if (res != ESP_OK) return res;

    char part_buf[64];

    while (true) {
        if (!have_frame) {
            vTaskDelay(pdMS_TO_TICKS(50));
            continue;
        }

        if (xSemaphoreTake(frame_mutex, pdMS_TO_TICKS(200)) != pdTRUE) {
            continue;
        }
        // Take a local copy of length/pointer while holding the lock,
        // then release before the (potentially slow) network write.
        size_t len = latest_frame_len;
        // NOTE: for simplicity we send directly out of latest_frame_buf
        // while still holding the mutex, briefly blocking the UVC
        // callback. Fine for this frame rate / size; revisit if you see
        // dropped frames under load.
        res = httpd_resp_send_chunk(req, STREAM_BOUNDARY, strlen(STREAM_BOUNDARY));
        if (res == ESP_OK) {
            size_t hlen = snprintf(part_buf, sizeof(part_buf), STREAM_PART, (unsigned)len);
            res = httpd_resp_send_chunk(req, part_buf, hlen);
        }
        if (res == ESP_OK) {
            res = httpd_resp_send_chunk(req, (const char *)latest_frame_buf, len);
        }
        xSemaphoreGive(frame_mutex);

        if (res != ESP_OK) {
            ESP_LOGW(TAG, "Stream client disconnected");
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(30));
    }
    return res;
}

static httpd_handle_t start_webserver(void)
{
    httpd_handle_t server = NULL;
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.stack_size = 8192;

    if (httpd_start(&server, &config) == ESP_OK) {
        httpd_uri_t capture_uri = {
            .uri = "/capture",
            .method = HTTP_GET,
            .handler = capture_handler,
        };
        httpd_register_uri_handler(server, &capture_uri);

        httpd_uri_t stream_uri = {
            .uri = "/stream",
            .method = HTTP_GET,
            .handler = stream_handler,
        };
        httpd_register_uri_handler(server, &stream_uri);
    }
    return server;
}

// ---------------------------------------------------------------------
// USB Host / UVC setup
// ---------------------------------------------------------------------
static void uvc_camera_init(void)
{
    xfer_buffer_a = (uint8_t *)heap_caps_malloc(XFER_BUFFER_SIZE, MALLOC_CAP_SPIRAM);
    xfer_buffer_b = (uint8_t *)heap_caps_malloc(XFER_BUFFER_SIZE, MALLOC_CAP_SPIRAM);
    uvc_frame_buffer = (uint8_t *)heap_caps_malloc(FRAME_BUFFER_SIZE, MALLOC_CAP_SPIRAM);
    latest_frame_buf = (uint8_t *)heap_caps_malloc(MAX_JPEG_FRAME_SIZE, MALLOC_CAP_SPIRAM);

    if (!xfer_buffer_a || !xfer_buffer_b || !uvc_frame_buffer || !latest_frame_buf) {
        ESP_LOGE(TAG, "Failed to allocate USB/frame buffers from PSRAM - check PSRAM is enabled");
        return;
    }

    uvc_config_t uvc_config = {
        .frame_width = FRAME_RESOLUTION_ANY,
        .frame_height = FRAME_RESOLUTION_ANY,
        .frame_interval = FPS2INTERVAL(15),
        .xfer_buffer_size = XFER_BUFFER_SIZE,
        .xfer_buffer_a = xfer_buffer_a,
        .xfer_buffer_b = xfer_buffer_b,
        .frame_buffer_size = FRAME_BUFFER_SIZE,
        .frame_buffer = uvc_frame_buffer,
        .frame_cb = &camera_frame_cb,
        .frame_cb_arg = NULL,
    };

    esp_err_t ret = uvc_streaming_config(&uvc_config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uvc_streaming_config failed: %s", esp_err_to_name(ret));
        return;
    }

    ret = usb_streaming_start();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "usb_streaming_start failed: %s", esp_err_to_name(ret));
        return;
    }

    ESP_LOGI(TAG, "USB UVC streaming started - waiting for webcam frames...");
}

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());

    frame_mutex = xSemaphoreCreateMutex();

    wifi_init_sta();

    esp_netif_ip_info_t ip_info;
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_get_ip_info(netif, &ip_info);
    ESP_LOGI(TAG, "======================================================");
    ESP_LOGI(TAG, " MJPEG stream will be at: http://" IPSTR "/stream", IP2STR(&ip_info.ip));
    ESP_LOGI(TAG, " Snapshot will be at:     http://" IPSTR "/capture", IP2STR(&ip_info.ip));
    ESP_LOGI(TAG, "======================================================");

    start_webserver();
    uvc_camera_init();
}
