from decimal import Decimal
from app.reasons import sources
from app.errors import DomainError

def evaluate(rows,context):
    intake=context.get("intake")
    bad=context.get("quarantine",[])
    accepted=set(x for row in rows for x in sources(row))
    rejected=set(x for row in bad for x in sources(row))
    if accepted & rejected: raise DomainError("LINEAGE_OVERLAP","同一来源行被重复裁决")
    m={"accepted_inputs":len(accepted),"quarantine_inputs":len(rejected),"output_records":len(rows)}
    if intake:
        excluded=intake["duplicate"]+intake["blank"]+intake["repeated_headers"]
        m.update(input=intake["input"],excluded=excluded,balanced=intake["input"]==len(accepted)+len(rejected)+excluded)
    else:m.update(input=len(accepted)+len(rejected),excluded=0,balanced=True)
    output=[]
    for row in rows:
        expected=Decimal(str(row.get("expected","0")));reported=Decimal(str(row.get("reported","0")))
        output.append({**row,"difference":str(expected-reported),"status":"通过" if expected==reported else "差异"})
    m.update(expected_total=str(sum((Decimal(str(r.get("expected","0"))) for r in rows),Decimal(0))),reported_total=str(sum((Decimal(str(r.get("reported","0"))) for r in rows),Decimal(0))),differences=sum(r["status"]=="差异" for r in output))
    receivables={}
    for row in output:
        key=(str(row.get("card","")),str(row.get("business_day","")))
        receivables[key]=receivables.get(key,Decimal(0))+Decimal(str(row.get("expected","0")))
    if any(total<0 for total in receivables.values()): raise DomainError("NEGATIVE_RECEIVABLE","卡日应收不能为负")
    for row in output:
        key="|".join((str(row.get("card","")),str(row.get("business_day",""))))
        if row.get("receivable_key") not in (None,key): raise DomainError("RECEIVABLE_KEY_MISMATCH","卡日应收键不一致")
        row["receivable_key"]=key
        row["day_receivable"]=str(receivables[(str(row.get("card","")),str(row.get("business_day","")))])
    m["receivables"]=len(receivables)
    m["receivable_total"]=str(sum(receivables.values(),Decimal(0)))
    return {"rows":output,"quarantine":[],"metrics":m}
