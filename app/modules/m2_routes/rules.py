from app.reasons import reject
from app.modules.m2_routes.stations import ROUTE_ALIASES, station

def evaluate(rows,context):
    profile=(context or {}).get("parameters",{}).get("station_profile")
    good=[];bad=[]
    for row in rows:
        route=ROUTE_ALIASES.get(row.get("route"))
        if not route:bad.append(reject(row,"UNKNOWN_ROUTE","线路未登记"));continue
        if not row.get("card"):bad.append(reject(row,"EMPTY_CARD","卡号为空"));continue
        detail=station(profile,route) or {"station":"未登记","type":"unknown"}
        good.append({**row,"route":route,"line_group":"city","station":detail["station"],"station_type":detail["type"]})
    return {"rows":good,"quarantine":bad,"metrics":{"routes":len(set(r["route"] for r in good)),"accepted":len(good)}}
