import csv,io,json
def build_archive(run):
    stream=io.StringIO(newline="");writer=csv.writer(stream)
    writer.writerow(["run_id","input_sha256","rule_version","kind","source_lines","reason","evidence","station_profile"])
    meta=run["manifest"];profile=meta.get("parameters",{}).get("station_profile") or {}
    profile_version=profile.get("version","默认资料") if isinstance(profile,dict) else "默认资料"
    for row in run["stages"][-1]["rows"]:
        evidence={key:row.get(key) for key in ("event_id","card","route","station","station_type","transfer_anchor","transfer_station","transfer_station_type","transfer_limit","interval_minutes","station_basis","basis_status","base_fare","transfer_discount","cap_discount","expected","day_paid","day_cap","day_receivable","receivable_key","reported","difference","status") if key in row}
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"accepted",json.dumps(row.get("_sources",[])),row.get("status",""),json.dumps(evidence,ensure_ascii=False),profile_version])
    for row in run["stages"][-1].get("cumulative_quarantine",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"quarantine",json.dumps(row.get("_sources",[])),row.get("reason",""),json.dumps(row,ensure_ascii=False),profile_version])
    for row in run["stages"][-1].get("receivables",[]):
        writer.writerow([run["run_id"],meta["input_sha256"],meta["rule_version"],"receivable",json.dumps([]),"",json.dumps(row,ensure_ascii=False),profile_version])
    return "﻿"+stream.getvalue()
