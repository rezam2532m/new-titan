"""Best-effort geolocation for node addresses (hostname/IP -> country).

Used to fill a node's city/country/country_code/flag automatically so every
server shows the flag of the country it is hosted in, without manual entry.
"""
import ipaddress
import os
import re
import socket
import unicodedata

import httpx

from .colo_map import COLO_MAP, COUNTRY_CODE

_IP_API = "http://ip-api.com/json/{ip}?fields=status,country,countryCode,city"

# Railway provides the replica's deployment region to each process. This is a
# better location source than resolving its public domain: Railway domains may
# terminate at a shared/anycast edge whose IP geolocation is not the replica's
# region. Keep this list aligned with Railway's currently documented regions.
_RAILWAY_REGIONS = {
    "us-west2": ("California", "United States", "US"),
    "us-east4": ("Virginia", "United States", "US"),
    "europe-west4": ("Amsterdam", "Netherlands", "NL"),
    "asia-southeast1": ("Singapore", "Singapore", "SG"),
}

_COUNTRY_ALIASES = {
    "united states of america": "US", "usa": "US", "us": "US",
    "uk": "GB", "great britain": "GB", "england": "GB",
    "turkiye": "TR", "türkiye": "TR", "czech republic": "CZ",
    "iran, islamic republic of": "IR", "russian federation": "RU",
    "hong kong sar": "HK",
    # Common Persian country names, for older/manual node records without ISO codes.
    "ایالات متحده": "US", "آمریکا": "US", "انگلستان": "GB",
    "بریتانیا": "GB", "ترکیه": "TR", "چک": "CZ", "جمهوری چک": "CZ",
    "آلمان": "DE", "هلند": "NL", "ایران": "IR", "فرانسه": "FR",
    "اسپانیا": "ES", "ایتالیا": "IT", "سوئیس": "CH", "سوئد": "SE",
    "نروژ": "NO", "دانمارک": "DK", "فنلاند": "FI", "بلژیک": "BE",
    "اتریش": "AT", "لهستان": "PL", "سنگاپور": "SG", "ژاپن": "JP",
    "هند": "IN", "استرالیا": "AU", "کانادا": "CA", "امارات": "AE",
    "امارات متحده عربی": "AE", "عربستان": "SA", "عربستان سعودی": "SA",
    "روسیه": "RU", "گرجستان": "GE", "ارمنستان": "AM", "آذربایجان": "AZ",
    "مصر": "EG", "قطر": "QA", "عمان": "OM", "بحرین": "BH", "کویت": "KW",
}


def flag_from_code(code: str) -> str:
    """Regional-indicator emoji from a 2-letter ISO country code."""
    code = (code or "").upper().strip()
    if re.fullmatch(r"[A-Z]{2}", code):
        return "".join(chr(0x1F1E6 + (ord(c) - ord("A"))) for c in code)
    return "🏳️"


def railway_location(region: str | None = None) -> dict:
    """Return the location of this Railway replica from its own region variable.

    The value can include Railway's region suffix (for example
    ``europe-west4-drams3a``), so match the stable region prefix rather than a
    public domain or a Cloudflare egress colo. Unknown regions remain explicitly
    unknown rather than falling back to a potentially misleading edge location.
    """
    value = str(region if region is not None else os.environ.get("RAILWAY_REPLICA_REGION", ""))
    value = value.strip().lower()
    if not value:
        return {}
    for prefix, (city, country, code) in _RAILWAY_REGIONS.items():
        if value == prefix or value.startswith(prefix + "-"):
            return {
                "city": city,
                "country": country,
                "country_code": code,
                "flag": flag_from_code(code),
                "region": value,
                "known": True,
            }
    # Do not silently substitute a Cloudflare edge or a public-domain IP for
    # an unrecognized deployment region: that would turn an unknown into a
    # plausible-looking but potentially wrong country.
    return {"city": "", "country": "", "country_code": "", "flag": "🌐",
            "region": value, "known": False}


def _normalized_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return re.sub(r"\s+", " ", value)


def country_code_for_location(country: str = "", city: str = "") -> str:
    """Infer an ISO country code from a known country or city name, if possible."""
    country_key = _normalized_name(country)
    if country_key:
        if country_key in _COUNTRY_ALIASES:
            return _COUNTRY_ALIASES[country_key]
        for name, code in COUNTRY_CODE.items():
            if _normalized_name(name) == country_key:
                return code
    city_key = _normalized_name(city)
    if city_key:
        for _colo, (known_city, known_country, _flag) in COLO_MAP.items():
            if _normalized_name(known_city) == city_key:
                for name, code in COUNTRY_CODE.items():
                    if _normalized_name(name) == _normalized_name(known_country):
                        return code
    return ""


def flag_for_location(country_code: str = "", country: str = "", city: str = "",
                      existing_flag: str = "") -> tuple[str, str]:
    """Return a normalized ``(country_code, flag)`` pair for a node location.

    A known ISO code always wins over a stale/mismatched stored emoji. If only a
    recognizable country or Cloudflare city is stored, infer its code. A neutral
    globe is used only when the location itself is unknown, so a node never has
    an empty flag slot or a made-up country flag.
    """
    code = str(country_code or "").strip().upper()
    if code == "UK":
        code = "GB"
    elif not re.fullmatch(r"[A-Z]{2}", code):
        code = country_code_for_location(country, city)
    if code:
        return code, flag_from_code(code)
    flag = str(existing_flag or "").strip()
    if flag and flag not in ("🏳️", "🌐"):
        indicators = [ch for ch in flag if 0x1F1E6 <= ord(ch) <= 0x1F1FF]
        if len(indicators) == 2:
            return "", flag
    return "", "🌐"


def _is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


def detect_location(address: str, timeout: float = 3.0) -> dict:
    """Resolve a node address to {city, country, country_code, flag}.

    Returns {} on any failure (no network, private IP, unknown host, …) so the
    caller can fall back to whatever the admin typed.
    """
    host = (address or "").strip()
    if not host:
        return {}
    # strip scheme, path/query, port and any userinfo
    # strip scheme, userinfo, path and port — keep IPv6 brackets handling
    host = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", host)
    host = host.split("/", 1)[0].rsplit("@", 1)[-1].strip()
    # Handle [IPv6]:port → IPv6
    if host.startswith("[") and "]" in host:
        host = host[1:host.index("]")]
    else:
        host = re.sub(r":\d+$", "", host)
    host = host.strip().strip("[]")
    if not host:
        return {}
    try:
        # Use getaddrinfo to support both IPv4 and IPv6; prefer first result
        if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host) or ":" in host:
            # Already an IP (v4 or v6)
            ip = host
            # Validate
            ipaddress.ip_address(ip)
        else:
            infos = socket.getaddrinfo(host, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
            ip = infos[0][4][0] if infos else ""
        if _is_private(ip) or ip in ("0.0.0.0", "255.255.255.255"):
            return {}
        r = httpx.get(_IP_API.format(ip=ip), timeout=timeout)
        d = r.json()
        if d.get("status") != "success":
            return {}
        cc = (d.get("countryCode") or "").strip().upper()[:2]
        return {
            "city": (d.get("city") or "").strip()[:64],
            "country": (d.get("country") or "").strip()[:64],
            "country_code": cc,
            "flag": flag_from_code(cc),
        }
    except Exception:  # noqa: BLE001 — best-effort only
        return {}


def detect_egress_location(timeout: float = 3.0) -> dict:
    """Best-effort location of this process's public egress IP.

    Used only when the hosting platform does not expose a replica-region
    variable. This is preferable to treating a Cloudflare request colo or the
    public service-domain IP as the server's location. Failure stays unknown.
    """
    try:
        response = httpx.get(
            "http://ip-api.com/json/?fields=status,country,countryCode,city",
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "success":
            return {}
        city = (data.get("city") or "").strip()[:64]
        country = (data.get("country") or "").strip()[:64]
        code, flag = flag_for_location(data.get("countryCode") or "", country, city)
        return {"city": city, "country": country, "country_code": code, "flag": flag}
    except Exception:  # noqa: BLE001 — best-effort only
        return {}
