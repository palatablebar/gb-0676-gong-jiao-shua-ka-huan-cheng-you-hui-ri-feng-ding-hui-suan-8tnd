import sqlite3,json
from datetime import datetime,timezone
from app.config import DATA_DIR
from app.errors import DomainError
from app.modules.m2_routes import stations

def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"records.db",timeout=20)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY,payload TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1,decision TEXT NOT NULL DEFAULT '待复核')")
    db.execute("CREATE TABLE IF NOT EXISTS station_profiles (version TEXT PRIMARY KEY,payload TEXT NOT NULL,digest TEXT NOT NULL,activated_at TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 0)")
    db.execute("CREATE TABLE IF NOT EXISTS receivables (run_id TEXT NOT NULL,receivable_key TEXT NOT NULL,card TEXT NOT NULL,business_day TEXT NOT NULL,amount TEXT NOT NULL,PRIMARY KEY(run_id,receivable_key))")
    return db

def save(run_id,payload):
    """原子写入批次与卡日应收台账。同源重跑 run_id 相同，台账不重复占用额度。"""
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,payload) VALUES (?,?)",(run_id,json.dumps(payload,ensure_ascii=False)))
        for row in payload["stages"][-1].get("receivables",[]):
            key=row["receivable_key"];card,_,day=key.partition("|")
            db.execute("INSERT OR IGNORE INTO receivables(run_id,receivable_key,card,business_day,amount) VALUES (?,?,?,?,?)",(run_id,key,card,day,row["amount"]))
    return get(run_id)

def get(run_id):
    with connect() as db: row=db.execute("SELECT payload,version,decision FROM runs WHERE id=?",(run_id,)).fetchone()
    if not row: raise DomainError("NOT_FOUND","批次不存在",404)
    return {**json.loads(row[0]),"version":row[1],"decision":row[2]}

def latest():
    with connect() as db: row=db.execute("SELECT id FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
    return get(row[0]) if row else None

def history():
    with connect() as db: return [{"run_id":i,"version":v,"decision":d} for i,v,d in db.execute("SELECT id,version,decision FROM runs ORDER BY rowid DESC")]

def run_receivables(run_id):
    with connect() as db: return [{"receivable_key":k,"card":c,"business_day":d,"amount":a} for k,c,d,a in db.execute("SELECT receivable_key,card,business_day,amount FROM receivables WHERE run_id=? ORDER BY receivable_key",(run_id,))]

def occupied_quota():
    """卡日额度占用：每张卡每个业务日只占一份额度。

    同一批次重跑因主键相同不会新增台账行；不同批次若覆盖同一卡日，也只
    计一次额度，并列出引用该卡日的批次与是否存在金额分歧。
    """
    with connect() as db:
        rows=list(db.execute("SELECT receivable_key,card,business_day,amount,run_id,rowid FROM receivables ORDER BY receivable_key,rowid"))
    quota={}
    for key,card,day,amount,run_id,rowid in rows:
        entry=quota.setdefault(key,{"receivable_key":key,"card":card,"business_day":day,"amount":amount,"runs":[],"conflict":False})
        if run_id not in entry["runs"]: entry["runs"].append(run_id)
        if amount!=entry["amount"]: entry["conflict"]=True
    return [{**entry,"runs":len(entry["runs"])} for entry in quota.values()]

def review(run_id,version,decision):
    if decision not in {"已复核","退回复核"}: raise DomainError("BAD_DECISION","复核状态无效")
    with connect() as db:
        row=db.execute("SELECT payload FROM runs WHERE id=?",(run_id,)).fetchone()
        if not row: raise DomainError("NOT_FOUND","批次不存在",404)
        if decision=="已复核": _assert_sealable(json.loads(row[0]))
        cursor=db.execute("UPDATE runs SET version=version+1,decision=? WHERE id=? AND version=?",(decision,run_id,version))
        if cursor.rowcount!=1: raise DomainError("STALE_VERSION","版本已更新，请刷新",409)
    return get(run_id)

def _assert_sealable(payload):
    final=payload["stages"][-1]["metrics"]
    if final.get("pending_basis"): raise DomainError("UNVERIFIED_BASIS",f"有 {final['pending_basis']} 笔换乘的站点依据未核清，不能封存",409)
    clearing=payload["stages"][5]["metrics"]
    if not clearing.get("balanced",True): raise DomainError("UNBALANCED","来源行未对平，不能封存",409)
    if not final.get("ready"): raise DomainError("NOT_READY","日结未就绪，不能封存",409)

def active_profile():
    """当前生效的站点资料；未切换过时使用仓内默认资料。"""
    with connect() as db: row=db.execute("SELECT payload FROM station_profiles WHERE active=1 ORDER BY activated_at DESC LIMIT 1").fetchone()
    return json.loads(row[0]) if row else stations.DEFAULT_PROFILE

def profile_history():
    with connect() as db: return [{"version":v,"digest":d,"active":bool(a),"activated_at":t} for v,d,t,a in db.execute("SELECT version,digest,activated_at,active FROM station_profiles ORDER BY activated_at DESC")]

def switch_profile(profile):
    """切换站点资料。先完整校验，再在一个事务内落库并切换 active。

    校验或写入任一步失败都会回滚：旧资料行、旧批次日账与旧日结归档保持原样。
    相同内容重复切换不会产生新版本，也不会重复计入额度。
    """
    clean=stations.validate(profile)
    digest=stations.digest(clean);now=datetime.now(timezone.utc).isoformat()
    with connect() as db:
        existing=db.execute("SELECT digest FROM station_profiles WHERE version=?",(clean["version"],)).fetchone()
        if existing:
            if existing[0]!=digest: raise DomainError("PROFILE_VERSION_CONFLICT","同版本站点资料内容不一致，请更换版本号",409)
            db.execute("UPDATE station_profiles SET active=CASE WHEN version=? THEN 1 ELSE 0 END",(clean["version"],))
            return {"version":clean["version"],"digest":digest,"active":True,"unchanged":True}
        db.execute("UPDATE station_profiles SET active=0")
        db.execute("INSERT INTO station_profiles(version,payload,digest,activated_at,active) VALUES (?,?,?,?,1)",(clean["version"],json.dumps(clean,ensure_ascii=False),digest,now))
        return {"version":clean["version"],"digest":digest,"active":True,"unchanged":False}
