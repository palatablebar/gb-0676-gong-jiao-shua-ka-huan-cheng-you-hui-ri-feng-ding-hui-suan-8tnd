from decimal import Decimal
from app.values import number,instant,money
from app.errors import DomainError
from app.modules.m2_routes.stations import transfer_basis

def evaluate(rows,context):
    params=(context or {}).get("parameters",{})
    profile=params.get("station_profile")
    cap=number(params.get("daily_cap","6.00"));off=number(params.get("transfer_discount","1.00"))
    overrides={}
    if params.get("transfer_minutes") is not None: overrides["normal"]=number(params["transfer_minutes"])
    if params.get("hub_transfer_minutes") is not None: overrides["hub"]=number(params["hub_transfer_minutes"])
    if cap<0 or off<0 or any(v<0 for v in overrides.values()):raise DomainError("BAD_DISCOUNT","优惠参数不能为负")
    spent={};anchor={};good=[];pending_basis=0
    for row in sorted(rows,key=lambda r:(r["card"],instant(r["at"]),r["event_id"])):
        key=(row["card"],row["business_day"]);base=number(row["base_fare"]);previous=anchor.get(key)
        eligible=False;basis=None;delta=None;pending=False
        if previous and previous["route"]!=row["route"]:
            limit,basis=transfer_basis(profile,previous["route"],row["route"],overrides)
            delta=Decimal(str((instant(row["at"])-instant(previous["at"])).total_seconds()))/60
            if basis["basis_status"]=="待核":pending=True
            else:eligible=Decimal(0)<=delta<Decimal(limit)
        if pending:pending_basis+=1
        transfer=min(base,off) if eligible else Decimal(0)
        after_transfer=base-transfer;remaining=max(Decimal(0),cap-spent.get(key,Decimal(0)));charge=min(after_transfer,remaining)
        cap_discount=after_transfer-charge;spent[key]=spent.get(key,Decimal(0))+charge
        good.append({**row,
            "transfer_anchor":("待核" if pending else previous["event_id"]) if previous else "—",
            "transfer_station":basis["station"] if basis else "—",
            "transfer_station_type":basis["station_type"] if basis else "—",
            "transfer_limit":basis["transfer_limit"] if basis else "—",
            "interval_minutes":money(delta) if delta is not None else "—",
            "station_basis":basis["station_basis"] if basis else ("同线路不适用换乘优惠" if previous else "无上一程付费行程"),
            "basis_status":("待核" if pending else basis["basis_status"]) if basis else "已核清",
            "transfer_discount":money(transfer),"cap_discount":money(cap_discount),"expected":money(charge),"day_paid":money(spent[key]),
            "daily_cap":money(cap),"receivable_key":row["card"]+"|"+row["business_day"]})
        if charge>0:anchor[key]=row
    receivable={}
    for row in good:
        key=(row["card"],row["business_day"])
        receivable[key]=receivable.get(key,Decimal(0))+number(row["expected"])
    for row in good:
        row["day_receivable"]=money(receivable[(row["card"],row["business_day"])])
        row["day_cap"]=money(cap)
    return {"rows":good,"quarantine":[],"metrics":{
        "expected_total":money(sum((number(r["expected"]) for r in good),Decimal(0))),
        "daily_caps":len(spent),"transfer_hits":sum(r["transfer_anchor"] not in ("—","待核") for r in good),
        "receivables":len(receivable),"unverified_basis":pending_basis,
        "station_profile":profile.get("version") if isinstance(profile,dict) else "默认资料"}}
