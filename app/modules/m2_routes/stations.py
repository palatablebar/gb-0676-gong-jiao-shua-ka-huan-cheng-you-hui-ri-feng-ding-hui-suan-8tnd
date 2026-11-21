"""站点资料与换乘时限裁决。

裁决结论：换乘时限不是全城统一值，而是由换乘涉及的站点类型决定。
枢纽站（机场/火车站）为 90 分钟，普通站为 60 分钟；两程中任一站为枢纽时，
按枢纽时限计算。这样 75 分钟的枢纽联程能享受优惠，而普通站的 75 分钟
换乘仍被 60 分钟半开区间排除，避免全城放宽后短途行程不断续优惠。

站点资料可整体切换。切换入口调用 validate() 做完整性校验：缺少线路、
类型非法或枢纽时限不高于普通时限都会在写库前失败，旧版资料与旧版日账
因此保持完整。运行期若资料仍有缺口（例如直接用 rows 预览），对应换乘
会被标记为“待核”，日结阶段据此拒绝封存。
"""
import hashlib
import json
from copy import deepcopy
from app.errors import DomainError
from app.values import number

ROUTE_ALIASES = {
    "01": "01", "1路": "01",
    "02": "02", "2路": "02",
    "03": "03", "3路": "03",
    "A1": "A1", "机场线": "A1",
    "R1": "R1", "火车站线": "R1",
}
CANONICAL_ROUTES = sorted(set(ROUTE_ALIASES.values()))

DEFAULT_PROFILE = {
    "version": "SP-2026.11.17",
    "limits": {"normal": 60, "hub": 90},
    "stations": {
        "01": {"station": "中央站", "type": "normal", "verified": True},
        "02": {"station": "北门站", "type": "normal", "verified": True},
        "03": {"station": "南门站", "type": "normal", "verified": True},
        "A1": {"station": "机场枢纽", "type": "hub", "verified": True},
        "R1": {"station": "火车站枢纽", "type": "hub", "verified": True},
    },
}
TYPE_LABELS = {"hub": "枢纽站", "normal": "普通站", "unknown": "类型未核"}


def _limit(value, field):
    try:
        parsed = number(value)
    except DomainError:
        raise DomainError("BAD_STATION_PROFILE", f"{field}时限必须是正数")
    if parsed <= 0 or parsed != parsed.to_integral_value():
        raise DomainError("BAD_STATION_PROFILE", f"{field}时限必须是正整数")
    return int(parsed)


def validate(profile):
    """严格校验一份准备切换上线的站点资料；失败时不产生任何写入。"""
    if not isinstance(profile, dict):
        raise DomainError("BAD_STATION_PROFILE", "站点资料需要对象")
    version = profile.get("version")
    if not isinstance(version, str) or not version.strip():
        raise DomainError("BAD_STATION_PROFILE", "站点资料缺少版本号")
    raw_limits = profile.get("limits")
    if not isinstance(raw_limits, dict):
        raise DomainError("BAD_STATION_PROFILE", "站点资料缺少时限表")
    limits = {"normal": _limit(raw_limits.get("normal"), "普通站"), "hub": _limit(raw_limits.get("hub"), "枢纽站")}
    if limits["hub"] <= limits["normal"]:
        raise DomainError("BAD_STATION_PROFILE", "枢纽站时限必须长于普通站时限")
    raw_stations = profile.get("stations")
    if not isinstance(raw_stations, dict) or not raw_stations:
        raise DomainError("BAD_STATION_PROFILE", "站点资料缺少站点清单")
    stations = {}
    for route, entry in raw_stations.items():
        canonical = ROUTE_ALIASES.get(route, route)
        if canonical not in CANONICAL_ROUTES:
            raise DomainError("BAD_STATION_PROFILE", f"站点资料含未登记线路：{route}")
        if not isinstance(entry, dict):
            raise DomainError("BAD_STATION_PROFILE", f"{route} 站点资料需要对象")
        name = entry.get("station")
        if not isinstance(name, str) or not name.strip():
            raise DomainError("BAD_STATION_PROFILE", f"{route} 缺少站点名称")
        if entry.get("type") not in ("hub", "normal"):
            raise DomainError("BAD_STATION_PROFILE", f"{route} 站点类型无效")
        if not isinstance(entry.get("verified", True), bool):
            raise DomainError("BAD_STATION_PROFILE", f"{route} 核验标记无效")
        stations[canonical] = {"station": name.strip(), "type": entry["type"], "verified": entry.get("verified", True)}
    missing = [route for route in CANONICAL_ROUTES if route not in stations]
    if missing:
        raise DomainError("BAD_STATION_PROFILE", "站点资料缺少线路：" + "、".join(missing))
    return {"version": version.strip(), "limits": limits, "stations": stations}


def runtime(profile=None):
    """运行期使用的容错视图：缺项从默认资料补齐，缺口保留为待核。"""
    profile = profile if isinstance(profile, dict) else {}
    base = deepcopy(DEFAULT_PROFILE)
    version = profile.get("version") if isinstance(profile.get("version"), str) and profile["version"].strip() else base["version"]
    raw_limits = profile.get("limits") if isinstance(profile.get("limits"), dict) else {}
    limits = dict(base["limits"])
    for key in ("normal", "hub"):
        if key in raw_limits:
            try:
                limits[key] = _limit(raw_limits[key], key)
            except DomainError:
                limits[key] = base["limits"][key]
    stations = deepcopy(base["stations"])
    raw_stations = profile.get("stations") if isinstance(profile.get("stations"), dict) else {}
    for route, entry in raw_stations.items():
        canonical = ROUTE_ALIASES.get(route, route)
        if canonical not in CANONICAL_ROUTES:
            continue
        if isinstance(entry, dict):
            station = entry.get("station")
            kind = entry.get("type")
            stations[canonical] = {
                "station": station.strip() if isinstance(station, str) and station.strip() else "未命名站点",
                "type": kind if kind in ("hub", "normal") else "unknown",
                "verified": bool(entry.get("verified", True)),
            }
        elif isinstance(entry, str) and entry.strip():
            stations[canonical] = {"station": entry.strip(), "type": "normal", "verified": True}
    return {"version": version.strip(), "limits": limits, "stations": stations}


def limit_for(profile, row, overrides=None):
    """回算阶段使用的容错时限：优先用上游带下的站点类型，否则查站点资料。"""
    data = runtime(profile)
    limits = dict(data["limits"])
    for key in ("normal", "hub"):
        if isinstance(overrides, dict) and overrides.get(key) is not None:
            limits[key] = int(overrides[key])
    kind = row.get("station_type")
    if kind not in ("hub", "normal"):
        detail = data["stations"].get(ROUTE_ALIASES.get(row.get("route"), row.get("route")))
        kind = detail["type"] if detail else "unknown"
    return limits[kind] if kind in limits else limits["normal"], kind


def digest(profile=None):
    payload = json.dumps(runtime(profile), sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def station(profile, route):
    return runtime(profile)["stations"].get(ROUTE_ALIASES.get(route, route))


def transfer_basis(profile, previous_route, current_route, overrides=None):
    """返回 (适用时限分钟, 依据字典)。

    两程任一站为枢纽即按枢纽时限；两站同为普通站时按普通时限。
    展示用站点取时限较长的一程（相同时取本程），因为步行时间由枢纽端决定。
    """
    data = runtime(profile)
    limits = dict(data["limits"])
    for key in ("normal", "hub"):
        if isinstance(overrides, dict) and overrides.get(key) is not None:
            limits[key] = int(overrides[key])
    previous = data["stations"].get(ROUTE_ALIASES.get(previous_route, previous_route))
    current = data["stations"].get(ROUTE_ALIASES.get(current_route, current_route))
    if not previous or not current or "unknown" in (previous["type"], current["type"]):
        return limits["normal"], {"station": "未登记", "station_type": "unknown", "transfer_limit": limits["normal"],
                "station_basis": f"站点资料缺失：{previous_route} → {current_route}", "basis_status": "待核", "hub": False}
    chosen, side = (current, "本程站点") if limits[current["type"]] >= limits[previous["type"]] else (previous, "上一程站点")
    limit = limits[chosen["type"]]
    verified = bool(previous.get("verified", True)) and bool(current.get("verified", True))
    label = TYPE_LABELS[chosen["type"]]
    basis = {
        "station": chosen["station"],
        "station_type": chosen["type"],
        "transfer_limit": limit,
        "station_basis": f"{chosen['station']}（{side}·{label}）·{limit}分钟",
        "basis_status": "已核清" if verified else "待核",
        "hub": chosen["type"] == "hub",
    }
    return limit, basis
