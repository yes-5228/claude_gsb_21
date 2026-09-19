"""台账合并 / 拆分、月度考核与归属留痕测试。"""

from datetime import datetime

import pytest

from tests.conftest import full_items


def _make_restroom(client, name, **extra):
    payload = {"name": name, "district": "变更测试区", "address": f"{name}地址"}
    payload.update(extra)
    resp = client.post("/api/v1/restrooms", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _open_issue(client, restroom_id, title="在办问题"):
    resp = client.post(
        "/api/v1/issues",
        json={"restroom_id": restroom_id, "title": title, "reporter": "巡查员"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _close_issue(client, issue_id):
    for target in ("整改中", "待验收", "已完成", "已关闭"):
        resp = client.post(
            f"/api/v1/issues/{issue_id}/transitions",
            json={"to_status": target, "operator": "值班长"},
        )
        assert resp.status_code == 200, resp.text


def _inspection(client, restroom_id, score=8.0):
    resp = client.post(
        "/api/v1/inspections",
        json={"restroom_id": restroom_id, "inspector": "巡查员", "items": full_items(score)},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _assess(client, restroom_id, period):
    resp = client.post(
        f"/api/v1/assessments/restrooms/{restroom_id}",
        json={"period": period, "issued_by": "考核员"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_merge(client, source_id, target_id):
    resp = client.post(
        "/api/v1/change-orders/merge",
        json={
            "source_restroom_id": source_id,
            "target_restroom_id": target_id,
            "reason": "两座公厕物理连通、管养主体合并，依据年度撤并计划执行",
            "applicant": "申请人",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _create_split(client, source_id, assignments, name="拆出新点位"):
    resp = client.post(
        "/api/v1/change-orders/split",
        json={
            "source_restroom_id": source_id,
            "new_restroom": {"name": name, "district": "变更测试区", "address": "新点位地址"},
            "issue_assignments": assignments,
            "reason": "区域改造需从既有公厕拆出独立点位，依据现场核查与批复文件",
            "applicant": "申请人",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_merge_reassigns_records_and_keeps_origin_code(client):
    source = _make_restroom(client, "合并-源厕")
    target = _make_restroom(client, "合并-承接厕")
    inspection = _inspection(client, source["id"])
    open_issue = _open_issue(client, source["id"], "待整改")
    closed_issue = _open_issue(client, source["id"], "将关闭")
    _close_issue(client, closed_issue["id"])
    period = datetime.now().strftime("%Y-%m")
    assessment = _assess(client, source["id"], period)

    order = _create_merge(client, source["id"], target["id"])
    approved = client.post(
        f"/api/v1/change-orders/{order['id']}/approve",
        json={"approver": "审批主任", "remark": "同意撤并"},
    )
    assert approved.status_code == 200, approved.text
    snapshot = approved.json()["result_snapshot"]
    assert snapshot["moved_inspection_count"] == 1
    assert snapshot["moved_issue_count"] == 2
    assert snapshot["moved_assessment_count"] == 1

    # 源厕标记为已撤并并指向承接方，台账仍可追溯
    detail = client.get(f"/api/v1/restrooms/{source['id']}").json()
    assert detail["status"] == "已撤并"
    assert detail["merged_into"]["id"] == target["id"]

    # 巡查、问题、考核的当前归属都到承接方，且保留源厕原编号
    moved_inspection = client.get(
        "/api/v1/inspections", params={"restroom_id": target["id"]}
    ).json()
    assert moved_inspection["meta"]["total"] == 1
    assert moved_inspection["items"][0]["id"] == inspection["id"]
    assert moved_inspection["items"][0]["origin_restroom_code"] == source["code"]

    moved_issue = client.get(f"/api/v1/issues/{open_issue['id']}").json()
    assert moved_issue["restroom_id"] == target["id"]
    assert moved_issue["origin_restroom_code"] == source["code"]
    assert any(record["action"] == "归属变更" for record in moved_issue["records"])

    target_assessments = client.get(
        "/api/v1/assessments", params={"restroom_id": target["id"]}
    ).json()
    assert len(target_assessments) == 1
    assert target_assessments[0]["id"] == assessment["id"]
    assert target_assessments[0]["origin_restroom_code"] == source["code"]
    assert (
        client.get("/api/v1/assessments", params={"restroom_id": source["id"]}).json() == []
    )


def test_inspection_submit_blocked_after_merge_with_successor_hint(client):
    source = _make_restroom(client, "拦截-源厕")
    target = _make_restroom(client, "拦截-承接厕")
    order = _create_merge(client, source["id"], target["id"])
    assert (
        client.post(
            f"/api/v1/change-orders/{order['id']}/approve", json={"approver": "主任"}
        ).status_code
        == 200
    )

    blocked = client.post(
        "/api/v1/inspections",
        json={"restroom_id": source["id"], "inspector": "巡查员", "items": full_items(9)},
    )
    assert blocked.status_code == 409
    assert target["code"] in blocked.json()["detail"]

    blocked_issue = client.post(
        "/api/v1/issues",
        json={"restroom_id": source["id"], "title": "撤并后上报"},
    )
    assert blocked_issue.status_code == 409


def test_split_assigns_open_issues_freezes_history(client):
    source = _make_restroom(client, "拆分-源厕")
    inspection = _inspection(client, source["id"])
    to_new = _open_issue(client, source["id"], "划到新点位")
    to_keep = _open_issue(client, source["id"], "留在原点位")
    closed = _open_issue(client, source["id"], "历史已关闭")
    _close_issue(client, closed["id"])
    period = datetime.now().strftime("%Y-%m")
    assessment = _assess(client, source["id"], period)

    order = _create_split(
        client,
        source["id"],
        [
            {"issue_id": to_new["id"], "destination": "new"},
            {"issue_id": to_keep["id"], "destination": "source"},
        ],
        name="拆分-新点位",
    )
    approved = client.post(
        f"/api/v1/change-orders/{order['id']}/approve",
        json={"approver": "审批主任", "remark": "同意拆分"},
    )
    assert approved.status_code == 200, approved.text
    snapshot = approved.json()["result_snapshot"]
    new_id = snapshot["new_restroom_id"]
    assert snapshot["moved_issue_ids"] == [to_new["id"]]
    assert snapshot["retained_issue_ids"] == [to_keep["id"]]

    # 未闭环问题按明确划归落到新点位，留原编号
    moved = client.get(f"/api/v1/issues/{to_new['id']}").json()
    assert moved["restroom_id"] == new_id
    assert moved["origin_restroom_code"] == source["code"]
    assert any(record["action"] == "归属变更" for record in moved["records"])

    # 留在原点位的在办问题、已关闭问题、历史巡查都不动
    assert client.get(f"/api/v1/issues/{to_keep['id']}").json()["restroom_id"] == source["id"]
    assert client.get(f"/api/v1/issues/{closed['id']}").json()["restroom_id"] == source["id"]
    kept_inspections = client.get(
        "/api/v1/inspections", params={"restroom_id": source["id"]}
    ).json()
    assert kept_inspections["meta"]["total"] == 1
    assert kept_inspections["items"][0]["id"] == inspection["id"]

    # 已出具的月度考核结果不随拆分迁移、不重算
    source_assessments = client.get(
        "/api/v1/assessments", params={"restroom_id": source["id"]}
    ).json()
    assert [item["id"] for item in source_assessments] == [assessment["id"]]
    assert client.get("/api/v1/assessments", params={"restroom_id": new_id}).json() == []

    new_detail = client.get(f"/api/v1/restrooms/{new_id}").json()
    assert new_detail["name"] == "拆分-新点位"
    assert new_detail["code"].startswith("WC-")


def test_split_requires_full_assignment_of_open_issues(client):
    source = _make_restroom(client, "拆分校验-源厕")
    issue = _open_issue(client, source["id"])

    # 在办问题未全覆盖 -> 拒绝
    missing = client.post(
        "/api/v1/change-orders/split",
        json={
            "source_restroom_id": source["id"],
            "new_restroom": {"name": "新点", "district": "变更测试区", "address": "x"},
            "issue_assignments": [],
            "reason": "未覆盖在办问题的拆分申请，依据说明文字补足长度",
        },
    )
    assert missing.status_code == 400
    assert str(issue["id"]) in missing.json()["detail"]

    # 划归了不属于该公厕在办问题的编号 -> 拒绝
    unknown = client.post(
        "/api/v1/change-orders/split",
        json={
            "source_restroom_id": source["id"],
            "new_restroom": {"name": "新点", "district": "变更测试区", "address": "x"},
            "issue_assignments": [{"issue_id": 999999, "destination": "new"}],
            "reason": "划归了不存在问题的拆分申请，依据说明文字补足长度",
        },
    )
    assert unknown.status_code == 400


def test_change_order_approval_workflow_and_guards(client):
    source = _make_restroom(client, "审批流-源厕")
    target = _make_restroom(client, "审批流-承接厕")

    # 同一公厕不能存在两张进行中的变更单
    first = _create_merge(client, source["id"], target["id"])
    duplicate = client.post(
        "/api/v1/change-orders/merge",
        json={
            "source_restroom_id": source["id"],
            "target_restroom_id": target["id"],
            "reason": "重复发起的合并申请，依据说明文字补足长度",
        },
    )
    assert duplicate.status_code == 409

    # 已执行后再次审批/驳回/撤销均被拒绝
    approve = client.post(
        f"/api/v1/change-orders/{first['id']}/approve", json={"approver": "主任"}
    )
    assert approve.status_code == 200
    for action in ("approve", "reject", "revoke"):
        resp = client.post(
            f"/api/v1/change-orders/{first['id']}/{action}", json={"approver": "主任"}
        )
        assert resp.status_code == 409, resp.text

    # 已撤并的公厕不能再发起合并
    again = client.post(
        "/api/v1/change-orders/merge",
        json={
            "source_restroom_id": source["id"],
            "target_restroom_id": target["id"],
            "reason": "对已撤并公厕再次发起合并，依据说明文字补足长度",
        },
    )
    assert again.status_code == 400


def test_reject_and_revoke_leave_records_untouched(client):
    source = _make_restroom(client, "驳回-源厕")
    target = _make_restroom(client, "驳回-承接厕")
    _inspection(client, source["id"])

    order = _create_merge(client, source["id"], target["id"])
    rejected = client.post(
        f"/api/v1/change-orders/{order['id']}/reject",
        json={"approver": "主任", "remark": "依据不足"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "已驳回"

    # 驳回后记录归属完全不变
    assert (
        client.get("/api/v1/inspections", params={"restroom_id": source["id"]}).json()[
            "meta"
        ]["total"]
        == 1
    )
    detail = client.get(f"/api/v1/restrooms/{source['id']}").json()
    assert detail["status"] == "正常开放"

    # 撤销路径：撤销后可以重新发起
    second_source = _make_restroom(client, "撤销-源厕")
    second_target = _make_restroom(client, "撤销-承接厕")
    pending = _create_merge(client, second_source["id"], second_target["id"])
    revoked = client.post(f"/api/v1/change-orders/{pending['id']}/revoke")
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "已撤销"
    recreated = _create_merge(client, second_source["id"], second_target["id"])
    assert recreated["status"] == "待审批"


def test_merge_rolls_back_entirely_on_failure(client, monkeypatch):
    from app.core.database import SessionLocal
    from app.core.constants import RestroomStatus
    from app.models import Inspection, Issue, Restroom, RestroomChangeOrder
    from app.schemas.change_order import ApprovalAction
    from app.services import change_order_service

    source = _make_restroom(client, "回滚-源厕")
    target = _make_restroom(client, "回滚-承接厕")
    _inspection(client, source["id"])
    _open_issue(client, source["id"])
    order = _create_merge(client, source["id"], target["id"])

    class SimulatedFailure(Exception):
        pass

    def boom(*args, **kwargs):
        raise SimulatedFailure("执行中途失败")

    monkeypatch.setattr(change_order_service, "RectificationRecord", boom)
    db = SessionLocal()
    try:
        with pytest.raises(SimulatedFailure):
            change_order_service.approve_order(
                db, order["id"], ApprovalAction(approver="主任")
            )
    finally:
        db.close()
    monkeypatch.undo()

    db = SessionLocal()
    try:
        src = db.get(Restroom, source["id"])
        tgt = db.get(Restroom, target["id"])
        assert src.status == RestroomStatus.NORMAL.value
        assert src.merged_into_id is None
        assert tgt.status == RestroomStatus.NORMAL.value
        # 没有出现记录只迁了一半：巡查/问题仍全部挂在源厕
        assert (
            db.query(Inspection).filter(Inspection.restroom_id == source["id"]).count() == 1
        )
        assert db.query(Issue).filter(Issue.restroom_id == target["id"]).count() == 0
        assert (
            db.query(Issue)
            .filter(Issue.restroom_id == source["id"], Issue.origin_restroom_id.isnot(None))
            .count()
            == 0
        )
        order_row = db.get(RestroomChangeOrder, order["id"])
        assert order_row.status == "待审批"
        assert order_row.result_snapshot is None
    finally:
        db.close()

    # 失败后单据仍可正常审批通过
    retried = client.post(
        f"/api/v1/change-orders/{order['id']}/approve", json={"approver": "主任"}
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "已执行"


def test_merged_restrooms_excluded_from_active_stats(client):
    source = _make_restroom(client, "统计-源厕")
    target = _make_restroom(client, "统计-承接厕")
    _inspection(client, source["id"], score=8.0)
    _open_issue(client, source["id"])
    order = _create_merge(client, source["id"], target["id"])
    client.post(f"/api/v1/change-orders/{order['id']}/approve", json={"approver": "主任"})

    default_list = client.get("/api/v1/restrooms").json()
    with_merged = client.get(
        "/api/v1/restrooms", params={"include_merged": "true"}
    ).json()
    ids_default = {item["id"] for item in default_list["items"]}
    # 默认列表不含已撤并公厕，含承接方；显式 include_merged 时都在
    assert source["id"] not in ids_default
    assert target["id"] in ids_default
    assert {item["id"] for item in with_merged["items"]} >= {source["id"], target["id"]}

    overview = client.get("/api/v1/stats/overview").json()
    assert overview["restroom_total"] == default_list["meta"]["total"]

    # 统计按现有归属重算：承接方详情包含迁入的巡查/问题，源厕已清零
    target_detail = client.get(f"/api/v1/restrooms/{target['id']}").json()
    assert target_detail["inspection_count"] == 1
    assert target_detail["total_issue_count"] == 1
    assert target_detail["open_issue_count"] == 1
    assert target_detail["avg_score"] == 80.0
    source_detail = client.get(f"/api/v1/restrooms/{source['id']}").json()
    assert source_detail["inspection_count"] == 0
    assert source_detail["total_issue_count"] == 0
    assert source_detail["avg_score"] is None


def test_assessment_freeze_and_duplicate_guard(client):
    restroom = _make_restroom(client, "考核-公厕")
    _inspection(client, restroom["id"], score=9.0)
    current_period = datetime.now().strftime("%Y-%m")

    first = _assess(client, restroom["id"], current_period)
    assert first["grade"] == "优秀"
    assert first["inspection_count"] == 1

    # 同一公厕同一月份不能重复出具
    dup = client.post(
        f"/api/v1/assessments/restrooms/{restroom['id']}",
        json={"period": current_period, "issued_by": "考核员"},
    )
    assert dup.status_code == 409

    # 合并后承接方已有一份当月（带来源）考核，仍可单独出具承接方当月考核
    target = _make_restroom(client, "考核-承接厕")
    order = _create_merge(client, restroom["id"], target["id"])
    client.post(f"/api/v1/change-orders/{order['id']}/approve", json={"approver": "主任"})
    target_assessments = client.get(
        "/api/v1/assessments", params={"restroom_id": target["id"]}
    ).json()
    assert len(target_assessments) == 1
    assert target_assessments[0]["origin_restroom_code"] == restroom["code"]
    second = client.post(
        f"/api/v1/assessments/restrooms/{target['id']}",
        json={"period": current_period, "issued_by": "考核员"},
    )
    assert second.status_code == 201, second.text
    # 承接方当月现存两条来源不同的历史考核（迁入 + 新出），互不覆盖
    both = client.get("/api/v1/assessments", params={"restroom_id": target["id"]}).json()
    assert {row["origin_restroom_code"] is None for row in both} == {True, False}
