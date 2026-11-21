from flask import render_template
from app.config import MODULES,TITLE,SHORT
from app.pipeline import execute,load_sample
from app.modules.m2_routes import stations
from app import store

CHOICES=[
    ['event_id','card','route','event_time','result','reported'],
    ['event_id','card','route','station','station_type'],
    ['event_id','card','fare_version','base_fare','reported','at'],
    ['journey','card','route','station','business_day','at'],
    ['event_id','card','route','transfer_station','transfer_station_type','interval_minutes','transfer_limit','station_basis','basis_status','transfer_discount','cap_discount','expected','day_paid','day_receivable'],
    ['event_id','card','receivable_key','expected','reported','difference','status'],
    ['event_id','card','receivable_key','day_receivable','expected','reported','status'],
]
LABELS={'event_id':'事件','card':'卡号','route':'线路','station':'站点','station_type':'站点类型','event_time':'刷卡时间','result':'刷卡状态',
    'reported':'实扣 / 元','line_group':'线路组','fare_version':'票价版','base_fare':'基础票价','at':'事件时间 UTC','journey':'行程编号',
    'business_day':'业务日','transfer_anchor':'锚点','transfer_station':'换乘站','transfer_station_type':'换乘站类型','transfer_limit':'适用时限 / 分','interval_minutes':'间隔 / 分',
    'station_basis':'站点依据','basis_status':'依据状态','transfer_discount':'换乘优惠','cap_discount':'封顶减免','expected':'应扣 / 元',
    'day_paid':'日累计','day_receivable':'当日应收 / 元','daily_cap':'封顶额度','receivable_key':'卡日键','difference':'差额 / 元','status':'结论',
    'accepted':'采纳行','versions':'版本','expected_total':'应扣总额','daily_caps':'卡日数量','transfer_hits':'换乘次数','input':'输入行',
    'quarantine':'隔离行','duplicate':'重复行','blank':'空白行','repeated_headers':'重复表头','encoding':'编码','routes':'线路数','cards':'卡数',
    'journeys':'行程数','records':'记录数','source_lines':'来源行数','sha256':'摘要','ready':'可归档','differences':'差异项',
    'accepted_inputs':'采纳来源行','quarantine_inputs':'隔离来源行','output_records':'结果记录','excluded':'排除行','balanced':'行数平衡',
    'reported_total':'申报合计','receivables':'卡日应收数','receivable_total':'应收合计','unverified_basis':'待核换乘','station_profile':'站点资料版',
    'pending_basis':'待核换乘','unique_receivable':'应收键一致','amount':'金额 / 元','runs':'占用批次'}
LABELS.update({'accepted':'采纳行','input':'输入行','quarantine':'隔离行'})

def register_pages(app):
    def page(index):
        run=store.latest() or execute(load_sample("dirty.csv"))
        stage=run["stages"][index]
        rows=stage["rows"]
        columns=CHOICES[index]
        transfers=[r for r in run["stages"][4]["rows"] if r.get("transfer_anchor") not in (None,"—","待核")]
        pending=[r for r in run["stages"][4]["rows"] if r.get("basis_status")=="待核"]
        daily=[]
        seen=set()
        for row in run["stages"][4]["rows"]:
            key=row.get("receivable_key")
            if key in seen: continue
            seen.add(key)
            daily.append({"receivable_key":key,"card":row.get("card"),"business_day":row.get("business_day"),
                "day_receivable":row.get("day_receivable"),"day_paid":row.get("day_paid"),"day_cap":row.get("daily_cap")})
        return render_template(f"m{index+1}.html",title=TITLE,short=SHORT,modules=MODULES,index=index,run=run,stage=stage,rows=rows,
            columns=columns,history=store.history(),labels=LABELS,transfers=transfers,pending=pending,daily=daily,
            profile=store.active_profile(),profile_history=store.profile_history(),station_types=stations.TYPE_LABELS,
            occupied=store.occupied_quota(),receivables=run["stages"][-1].get("receivables",[]))
    app.add_url_rule("/",view_func=lambda:page(4))
    for index,(slug,name) in enumerate(MODULES):
        app.add_url_rule("/"+slug,endpoint="page_"+slug,view_func=lambda index=index:page(index))
