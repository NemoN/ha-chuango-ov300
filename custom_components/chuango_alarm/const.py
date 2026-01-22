from homeassistant.const import Platform

DOMAIN = "chuango_alarm"

# Zone lookup (region -> server endpoints)
ZONE_API_BASE = "https://query.iotdreamcatcher.net.cn:12082"
ZONE_PATH = "/v2/server/zone"

# API paths (resolved via zone 'am' endpoint)
LOGIN_PATH = "/v2/user/login"
HOMES_PATH = "/v2/group/homes"

CONF_REGION = "region"              # e.g. 'DE'
CONF_COUNTRY_NAME = "country_name"  # e.g. 'Germany'
CONF_COUNTRY_CODE = "country_code"  # e.g. '+49'

CONF_EMAIL = "email"
CONF_PASSWORD_MD5 = "password_md5"
CONF_UUID = "uuid"

# Resolved endpoints from zone lookup
CONF_AM_DOMAIN = "am_domain"
CONF_AM_IP = "am_ip"
CONF_AM_PORT = "am_port"

CONF_MQTT_DOMAIN = "mqtt_domain"
CONF_MQTT_IP = "mqtt_ip"
CONF_MQTT_PORT = "mqtt_port"

DEFAULT_OS = "android"
DEFAULT_OS_VER = "29"
DEFAULT_APP = "com.dc.dreamcatcherlife"
DEFAULT_APP_VER = "2.2.1"
DEFAULT_PHONE_BRAND = "GOOGLE"
DEFAULT_LANG = "en"
DEFAULT_BRAND_HEADER = "dreamcatcher"

DEFAULT_USER_AGENT = (
    "Dalvik/2.1.0 (Linux; U; Android 10; Android SDK built for arm64 Build/QSR1.211112.010)"
)

PLATFORMS = [Platform.SENSOR]
