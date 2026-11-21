import hashlib,json
from decimal import Decimal
from app.errors import DomainError
from app.reasons import sources

def evaluate(rows,context):
    stages=[v for v in context.values() if isinstance(v,dict) and "metrics" in v]
    balances=[s["metrics"]["balanced"] for s in stages if "balanced" in s["metrics"]]
    if balances and not all(balances): raise DomainError("UNBALANCED","来源行未对平，不能归档")
    discounts=[s["metrics"] for s in stages if "unverified_basis" in s["metrics"]]
    pending=sum(m["unverified_basis"] for m in discounts)
    receivable_totals={}
    for row in rows:
        key=row.get("receivable_key")
        if key is None: raise DomainError("MISSING_RECEIVABLE","存在缺少卡日应收的记录，不能封存")
        total=str(row.get("day_receivable",row.get("expected","0")))
        if receivable_totals.setdefault(key,total)!=total: raise DomainError("RECEIVABLE_CONFLICT","同一卡日应收不一致")
    ids=[str(r.get("event_id",r.get("_line",""))) for r in rows]
    if len(ids)!=len(set(ids)): raise DomainError("ARCHIVE_DUPLICATE","归档业务键重复")
    receivable_rows=sorted(({"receivable_key":key,"amount":total} for key,total in receivable_totals.items()),key=lambda r:r["receivable_key"])
    encoded=json.dumps({"records":rows,"receivables":receivable_rows},ensure_ascii=False,sort_keys=True,default=str).encode()
    return {"rows":rows,"quarantine":[],"metrics":{"records":len(rows),"source_lines":len(set(x for row in rows for x in sources(row))),
        "sha256":hashlib.sha256(encoded).hexdigest(),"ready":pending==0,"differences":sum(r.get("status")=="差异" for r in rows),
        "receivables":len(receivable_totals),"receivable_total":str(sum((Decimal(v) for v in receivable_totals.values()),Decimal(0))),
        "pending_basis":pending},"receivables":receivable_rows}
