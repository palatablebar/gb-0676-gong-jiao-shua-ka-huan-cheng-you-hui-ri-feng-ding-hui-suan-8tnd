from decimal import Decimal
from app.modules.m5_discounts.rules import evaluate
from app.modules.m2_routes.stations import DEFAULT_PROFILE, transfer_basis, validate
from app.errors import DomainError
import pytest


def ride(id, minute, route="01", base="2.50", day="2026-11-16"):
    return {"event_id": str(id), "card": "0001", "business_day": day,
            "at": f"2026-11-16T{8 + minute // 60:02d}:{minute % 60:02d}:00Z", "route": route, "base_fare": base}


def window(pair_rows, profile=None):
    params = {"station_profile": profile or DEFAULT_PROFILE}
    return evaluate(pair_rows, {"parameters": params})["rows"]


def test_hub_transfer_75_minutes_gets_discount():
    "枢纽站时限 90 分钟：75 分钟联程不漏优惠"
    rows = window([ride(1, 0, "R1"), ride(2, 75, "01")])
    assert rows[1]["transfer_discount"] == "1.00" and rows[1]["transfer_limit"] == 90
    assert rows[1]["transfer_station_type"] == "hub" and rows[1]["basis_status"] == "已核清"


def test_normal_transfer_75_minutes_still_excluded():
    "普通站保持 60 分钟：全城不放宽，短途不续优惠"
    rows = window([ride(1, 0, "01"), ride(2, 75, "02")])
    assert rows[1]["transfer_discount"] == "0.00" and rows[1]["transfer_limit"] == 60


def test_hub_limit_applies_from_either_end():
    "上一程是枢纽也按枢纽时限"
    rows = window([ride(1, 0, "A1"), ride(2, 80, "02")])
    assert rows[1]["transfer_discount"] == "1.00" and rows[1]["transfer_station_type"] == "hub"


def test_hub_limit_is_still_half_open():
    "枢纽站同样半开区间：恰好 90 分钟排除"
    rows = window([ride(1, 0, "A1"), ride(2, 90, "01")])
    assert rows[1]["transfer_discount"] == "0.00"


def test_same_route_uses_no_transfer_limit():
    rows = window([ride(1, 0, "R1"), ride(2, 10, "R1")])
    assert rows[1]["transfer_discount"] == "0.00" and rows[1]["station_basis"] == "同线路不适用换乘优惠"


def test_one_receivable_per_card_day():
    "每张卡当日唯一应收，逐行汇总与日账一致"
    rows = window([ride(1, 0, "01"), ride(2, 10, "02"), ride(3, 20, "03"), ride(4, 90)])
    assert {r["receivable_key"] for r in rows} == {"0001|2026-11-16"}
    assert {r["day_receivable"] for r in rows} == {"6.00"}
    assert rows[-1]["day_paid"] == "6.00" and rows[-1]["daily_cap"] == "6.00"


def test_receivable_separate_cards():
    rows = window([ride(1, 0), {**ride(2, 10, "02"), "card": "0002"}])
    assert {r["receivable_key"] for r in rows} == {"0001|2026-11-16", "0002|2026-11-16"}


def test_unverified_station_blocks_discount_and_marks_pending():
    "资料缺口标记待核，不默认给优惠"
    profile = {"version": "T1", "limits": {"normal": 60, "hub": 90},
               "stations": {"01": {"station": "甲", "type": "normal", "verified": False},
                            "02": {"station": "乙", "type": "normal", "verified": True},
                            "03": {"station": "丙", "type": "normal", "verified": True},
                            "A1": {"station": "机场", "type": "hub", "verified": True},
                            "R1": {"station": "火车站", "type": "hub", "verified": True}}}
    result = evaluate([ride(1, 0, "01"), ride(2, 10, "02")], {"parameters": {"station_profile": profile}})
    assert result["rows"][1]["basis_status"] == "待核" and result["rows"][1]["transfer_discount"] == "0.00"
    assert result["metrics"]["unverified_basis"] == 1


def test_unknown_station_type_marks_pending():
    profile = {"version": "T2", "limits": {"normal": 60, "hub": 90},
               "stations": {"01": {"station": "甲", "type": "normal"}, "02": {"station": "乙", "type": "odd"}}}
    result = evaluate([ride(1, 0, "01"), ride(2, 10, "02")], {"parameters": {"station_profile": profile}})
    assert result["rows"][1]["basis_status"] == "待核"


def test_profile_must_cover_all_routes():
    with pytest.raises(DomainError) as e:
        validate({"version": "T3", "limits": {"normal": 60, "hub": 90}, "stations": {"01": {"station": "甲", "type": "normal"}}})
    assert e.value.code == "BAD_STATION_PROFILE"


def test_hub_limit_must_exceed_normal():
    with pytest.raises(DomainError):
        validate({"version": "T4", "limits": {"normal": 90, "hub": 60}, "stations": DEFAULT_PROFILE["stations"]})


def test_basis_station_is_the_longer_limit_end():
    limit, basis = transfer_basis(DEFAULT_PROFILE, "01", "A1")
    assert limit == 90 and basis["station"] == "机场枢纽" and basis["station_type"] == "hub"
