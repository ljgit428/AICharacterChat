"""基于出口 IP 的位置/时区自动检测（用户设置「自动对齐」后端）。

免费无 Key 的公共 IP 地理服务即可满足需求；主用 ipwho.is（支持 zh-CN 本地化），
失败时回退 ipapi.co。客户端是内网/回环地址时（本机开发、未配代理头的反代），
回退为按服务器自身出口 IP 检测——自部署场景下服务器通常与用户同一出口网络。
"""

import ipaddress
import logging

import requests

logger = logging.getLogger(__name__)

_GEO_TIMEOUT_SECONDS = 4


def get_client_ip(request):
    """取客户端出口 IP：优先 X-Forwarded-For 第一跳，其次 REMOTE_ADDR。"""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    for part in forwarded.split(","):
        candidate = part.strip()
        if candidate:
            return candidate
    return (request.META.get("REMOTE_ADDR") or "").strip()


def _is_public_ip(ip):
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (parsed.is_private or parsed.is_reserved or parsed.is_loopback or parsed.is_unspecified)


def _request_json(url, params=None):
    response = requests.get(url, params=params, timeout=_GEO_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("geo response is not an object")
    return payload


def _normalize_payload(payload, source, fallback_egress=False):
    country = str(payload.get("country") or payload.get("country_name") or "").strip()
    region = str(payload.get("region") or "").strip()
    city = str(payload.get("city") or "").strip()
    timezone = payload.get("timezone")
    if isinstance(timezone, dict):
        timezone = timezone.get("id")
    timezone = str(timezone or "").strip()

    if not any([country, region, city]):
        raise ValueError("geo response has no location fields")

    return {
        "ok": True,
        "source": source,
        "fallback_egress": fallback_egress,
        "country": country,
        "region": region,
        "city": city,
        "timezone": timezone,
        "latitude": payload.get("latitude"),
        "longitude": payload.get("longitude"),
    }


def detect_location(ip=None, lang="en"):
    """查询 IP 的地理位置与时区（含近似经纬度）；无法定位时 ok=False + reason。

    ip 为公网地址时按该 IP 查询；否则按查询发起方（即服务器出口）定位。
    """
    use_client_ip = bool(ip and _is_public_ip(ip))
    fallback_egress = not use_client_ip
    lang_param = "zh-CN" if str(lang).lower().startswith("zh") else "en"

    errors = []
    providers = [
        (
            "ipwho.is",
            "https://ipwho.is/",
            ({"ip": ip, "lang": lang_param} if use_client_ip else {"lang": lang_param}),
        ),
        ("ipapi.co", "https://ipapi.co/json/" if not use_client_ip else f"https://ipapi.co/{ip}/json/", None),
    ]
    for source, url, params in providers:
        try:
            payload = _request_json(url, params=params)
            if payload.get("success") is False:
                raise ValueError(payload.get("message") or "provider reported failure")
            return _normalize_payload(payload, source, fallback_egress=fallback_egress)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{source}: {exc}")

    logger.info("IP geo detection failed (fallback_egress=%s): %s", fallback_egress, "; ".join(errors))
    return {"ok": False, "reason": "unavailable"}


def detect_location_from_request(request, lang="en"):
    return detect_location(get_client_ip(request), lang=lang)
