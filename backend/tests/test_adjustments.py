"""合并/拆分：审批流、归属规则、原子回滚、考核冻结、提交确定性。"""

import threading
import time
from datetime import datetime

import pytest
from sqlalchemy.exc import OperationalError

from app.core.database import SessionLocal
from app.core.constants import AdjustmentStatus
from app.models import (
    Inspection,
    Issue,
    MonthlyAssessment,
    Restroom,
    RestroomAdjustment,
)
from app.schemas.inspection import InspectionCreate, InspectionItem
from app.services import adjustment_service, inspection_service
from tests.conftest import full_items

API = "/api/v1"


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def make_restroom(client, name="测试公厕", **kwargs):
    payload = {"name": name, "district": "测试区", "address": f"{name}地址"}
    payload.update(kwargs)
    response = client.post(f"{API}/restrooms", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_inspection(client, restroom_id, score=9.0, inspector="巡查员甲"):
    response = client.post(
        f"{API}/inspections",
        json={
            "restroom_id": restroom_id,
            "inspector": inspector,
            "items": full_items(score),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def make_issue(client, restroom_id, title="测试问题", **kwargs):
    payload = {"restroom_id": restroom_id, "title": title, "reporter": "巡查员甲"}
    payload.update(kwargs)
    response = client.post(f"{API}/issues", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def close_issue(client, issue_id, operator="值班长"):
    for target in ("整改中", "待验收", "已完成", "已关闭"):
        response = client.post(
            f"{API}/issues/{issue_id}/transitions",
            json={"to_status": target, "operator": operator},
        )
        assert response.status_code == 200, response.text
    return response.json()


def apply_merge(client, source_id, target_id, reason="两座公厕距离不足 50 米，管网合一，依规撤并整合"):
    response = client.post(
        f"{API}/restrooms/adjustments/merge",
        json={
            "source_restroom_id": source_id,
            "target_restroom_id": target_id,
            "reason": reason,
            "applicant": "台账管理员",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, adjustment_id, remark="同意"):
    response = client.post(
        f"{API}/restrooms/adjustments/{adjustment_id}/approve",
        json={"approver": "分管领导", "remark": remark},
    )
    return response


def counts(restroom_id):
    with SessionLocal() as db:
        inspection_count = (
            db.query(Inspection).filter(Inspection.restroom_id == restroom_id).count()
        )
        issue_count = db.query(Issue).filter(Issue.restroom_id == restroom_id).count()
        status = db.get(Restroom, restroom_id).status
    return inspection_count, issue_count, status


# ---------------------------------------------------------------------------
# 合并
# ---------------------------------------------------------------------------

def test_merge_transfers_all_records_and_keeps_original_code(client):
    source = make_restroom(client, "将被撤并公厕")
    target = make_restroom(client, "承接公厕")
    make_inspection(client, source["id"])
    make_issue(client, source["id"], "待整改问题")

    adjustment = apply_merge(client, source["id"], target["id"])
    assert adjustment["status"] == "待审批"
    assert adjustment["type"] == "合并"

    response = approve(client, adjustment["id"])
    assert response.status_code == 200, response.text
    done = response.json()
    assert done["status"] == "已完成"
    assert done["executed_at"] is not None

    # 源点位：记录全部归到承接方，档案保留并置为已撤并
    source_inspections, source_issues, source_status = counts(source["id"])
    assert (source_inspections, source_issues, source_status) == (0, 0, "已撤并")
    target_inspections, target_issues, target_status = counts(target["id"])
    assert target_inspections == 1
    assert target_issues == 1
    assert target_status == "正常开放"

    # 原编号可追溯到承接方
    traced = client.get(
        f"{API}/restrooms/adjustments/lineage", params={"code": source["code"]}
    ).json()
    assert len(traced) == 1
    assert traced[0]["relation"] == "merged_into"
    assert traced[0]["current_restroom_id"] == target["id"]
    assert traced[0]["moved_inspection_count"] == 1
    assert traced[0]["moved_issue_count"] == 1

    # 源点位详情仍可查，指向承接方
    detail = client.get(f"{API}/restrooms/{source['id']}").json()
    assert detail["status"] == "已撤并"
    assert detail["current_restroom"]["id"] == target["id"]
    assert any(link["original_code"] == source["code"] for link in detail["lineage"])

    # 审批轨迹完整
    actions = [log["action"] for log in done["logs"]]
    assert "提交申请" in actions and "审批通过并执行" in actions and "执行归属变更" in actions


def test_inspection_submitted_during_change_lands_on_determined_party(client):
    source = make_restroom(client, "撤并中公厕")
    target = make_restroom(client, "确定承接方")
    approve(client, apply_merge(client, source["id"], target["id"])["id"])

    # 归属变更后仍用原编号/原 ID 提交巡查 → 确定地落到承接方
    inspection = make_inspection(client, source["id"])
    assert inspection["restroom_id"] == target["id"]

    # 问题上报同样落到承接方；关联的巡查也在承接方名下，校验一致
    issue = make_issue(client, source["id"], "撤并后新问题", inspection_id=inspection["id"])
    assert issue["restroom_id"] == target["id"]

    # 服务层直接验证解析结果
    with SessionLocal() as db:
        resolved = adjustment_service.resolve_restroom(db, source["id"])
        assert resolved.id == target["id"]


# ---------------------------------------------------------------------------
# 拆分
# ---------------------------------------------------------------------------

def test_split_moves_open_issues_keeps_history(client):
    source = make_restroom(client, "将被拆分公厕")
    make_inspection(client, source["id"], score=8.0)
    open_issue = make_issue(client, source["id"], "在办任务-去新点位")
    closed_issue = make_issue(client, source["id"], "已闭环问题-留原点位")
    close_issue(client, closed_issue["id"])

    # 候选清单只含未闭环问题/在办任务
    movable = client.get(
        f"{API}/restrooms/adjustments/movable-issues",
        params={"restroom_id": source["id"]},
    ).json()
    assert [item["id"] for item in movable] == [open_issue["id"]]

    response = client.post(
        f"{API}/restrooms/adjustments/split",
        json={
            "source_restroom_id": source["id"],
            "reason": "该片区一分为二管养，东侧点位独立建档，明确在办问题归属",
            "applicant": "台账管理员",
            "new_restroom": {
                "name": "拆出的新点位",
                "district": "测试区",
                "address": "新点位路 8 号",
                "grade": "三类",
                "status": "正常开放",
            },
            "move_issue_ids": [open_issue["id"]],
        },
    )
    assert response.status_code == 201, response.text
    adjustment = response.json()
    assert adjustment["target_restroom_id"] is None  # 审批前新点位尚未创建

    done = approve(client, adjustment["id"]).json()
    assert done["status"] == "已完成"
    new_id = done["target_restroom_id"]
    assert new_id is not None

    new_restroom = client.get(f"{API}/restrooms/{new_id}").json()
    assert new_restroom["name"] == "拆出的新点位"

    # 未闭环问题划归新点位并追加划转轨迹；已闭环问题与历史巡查留在原点位
    moved = client.get(f"{API}/issues/{open_issue['id']}").json()
    assert moved["restroom_id"] == new_id
    assert moved["records"][-1]["action"] == "点位拆分划转"
    stayed_issue = client.get(f"{API}/issues/{closed_issue['id']}").json()
    assert stayed_issue["restroom_id"] == source["id"]

    source_inspections, source_issues, _ = counts(source["id"])
    assert source_inspections == 1
    assert source_issues == 1  # 只剩已闭环问题
    new_inspections, new_issues, _ = counts(new_id)
    assert (new_inspections, new_issues) == (0, 1)

    # 谱系记录
    links = client.get(f"{API}/restrooms/{new_id}/lineage").json()
    assert links[0]["relation"] == "split_from"
    assert links[0]["original_code"] == source["code"]
    assert links[0]["moved_issue_count"] == 1


def test_split_rejects_issues_not_belonging_or_closed(client):
    source = make_restroom(client, "拆分发起方")
    other = make_restroom(client, "无关公厕")
    foreign_issue = make_issue(client, other["id"], "别点位的问题")
    closed_here = make_issue(client, source["id"], "本点位已闭环")
    close_issue(client, closed_here["id"])

    response = client.post(
        f"{API}/restrooms/adjustments/split",
        json={
            "source_restroom_id": source["id"],
            "reason": "依据管养边界调整拆分点位，需要提供足够长的依据说明",
            "applicant": "台账管理员",
            "new_restroom": {"name": "无效新点位", "district": "测试区"},
            "move_issue_ids": [foreign_issue["id"], closed_here["id"]],
        },
    )
    assert response.status_code == 400
    assert "不能划归" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 审批流防护
# ---------------------------------------------------------------------------

def test_reject_changes_nothing_and_pending_blocks_new_application(client):
    a = make_restroom(client, "甲公厕")
    b = make_restroom(client, "乙公厕")
    c = make_restroom(client, "丙公厕")
    make_inspection(client, a["id"])

    adjustment = apply_merge(client, a["id"], b["id"])

    # 审批中：涉及点位不能再次发起调整
    conflict = client.post(
        f"{API}/restrooms/adjustments/merge",
        json={
            "source_restroom_id": b["id"],
            "target_restroom_id": c["id"],
            "reason": "审批中再次发起合并，应当被拒绝",
            "applicant": "台账管理员",
        },
    )
    assert conflict.status_code == 409

    # 审批中：档案不能删除
    assert client.delete(f"{API}/restrooms/{a['id']}", params={"force": "true"}).status_code == 409

    # 驳回：不产生任何归属变更
    rejected = client.post(
        f"{API}/restrooms/adjustments/{adjustment['id']}/reject",
        json={"approver": "分管领导", "remark": "依据不足"},
    ).json()
    assert rejected["status"] == "已驳回"
    a_inspections, _, a_status = counts(a["id"])
    assert a_inspections == 1 and a_status == "正常开放"

    # 已驳回的单据不能再次审批
    assert approve(client, adjustment["id"]).status_code == 409

    # 结案后可以正常提交巡查
    assert make_inspection(client, a["id"])["restroom_id"] == a["id"]


def test_cannot_merge_restroom_with_itself(client):
    a = make_restroom(client, "孤独公厕")
    response = client.post(
        f"{API}/restrooms/adjustments/merge",
        json={
            "source_restroom_id": a["id"],
            "target_restroom_id": a["id"],
            "reason": "自己并入自己应当被拒绝，这是足够长的依据说明文字",
            "applicant": "台账管理员",
        },
    )
    assert response.status_code == 400


def test_cannot_apply_against_merged_restroom(client):
    a = make_restroom(client, "第一次撤并方")
    b = make_restroom(client, "最终承接方")
    approve(client, apply_merge(client, a["id"], b["id"])["id"])

    # 已撤并点位不能再发起/参与调整
    response = client.post(
        f"{API}/restrooms/adjustments/merge",
        json={
            "source_restroom_id": a["id"],
            "target_restroom_id": b["id"],
            "reason": "已撤并点位不能再次参与调整，这是足够长的说明",
            "applicant": "台账管理员",
        },
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# 原子性：执行中途失败整体回滚
# ---------------------------------------------------------------------------

def test_execution_failure_rolls_back_everything(client, monkeypatch):
    source = make_restroom(client, "回滚源点位")
    target = make_restroom(client, "回滚承接方")
    make_inspection(client, source["id"])
    make_issue(client, source["id"], "不能只归一半的问题")
    adjustment = apply_merge(client, source["id"], target["id"])

    # 在归属变更写入后、事务提交前制造异常
    real_log = adjustment_service._log

    def boom(adj, action, operator, remark=None):
        if action == "执行归属变更":
            raise RuntimeError("模拟执行中断")
        real_log(adj, action, operator, remark)

    monkeypatch.setattr(adjustment_service, "_log", boom)

    with pytest.raises(RuntimeError):
        with SessionLocal() as db:
            adjustment_service.approve(
                db,
                adjustment["id"],
                type("Payload", (), {"approver": "分管领导", "remark": None})(),
            )

    # 业务数据完全不动：记录仍在源点位，源点位仍正常开放
    source_inspections, source_issues, source_status = counts(source["id"])
    assert (source_inspections, source_issues, source_status) == (1, 1, "正常开放")
    target_inspections, target_issues, _ = counts(target["id"])
    assert (target_inspections, target_issues) == (0, 0)

    # 单据标记为执行失败并留痕，可据此重新申请
    with SessionLocal() as db:
        failed = db.get(RestroomAdjustment, adjustment["id"])
        assert failed.status == AdjustmentStatus.FAILED.value
        assert failed.fail_reason
        assert any(log.action == "执行失败" for log in failed.logs)


# ---------------------------------------------------------------------------
# 统计按现有归属重算；月度考核结果不动
# ---------------------------------------------------------------------------

def test_stats_follow_attribution_but_monthly_assessments_freeze(client):
    source = make_restroom(client, "考核后撤并方")
    target = make_restroom(client, "考核后承接方")
    make_inspection(client, source["id"], score=4.0)
    make_issue(client, source["id"], "考核月内的问题")
    period = datetime.now().strftime("%Y-%m")

    # 1) 出具月度考核：源点位 1 次巡查、均分 40、不合格
    generated = client.post(
        f"{API}/assessments/generate",
        json={"period": period, "operator": "考核员"},
    ).json()
    source_snapshot = next(item for item in generated if item["restroom_id"] == source["id"])
    assert source_snapshot["inspection_count"] == 1
    assert source_snapshot["avg_score"] == 40.0
    assert source_snapshot["grade"] == "不合格"

    # 2) 合并撤并
    approve(client, apply_merge(client, source["id"], target["id"])["id"])

    # 3) 实时统计按现有归属：源点位不再计入在用点位总数，承接方详情含归入记录
    overview = client.get(f"{API}/stats/overview").json()
    with SessionLocal() as db:
        active_total = (
            db.query(Restroom).filter(Restroom.status != "已撤并").count()
        )
    assert overview["restroom_total"] == active_total
    # 已撤并档案仍保留在台账列表中可追溯
    listed = client.get(f"{API}/restrooms", params={"status": "已撤并"}).json()
    assert any(item["id"] == source["id"] for item in listed["items"])
    restroom_ids = {
        item["restroom_id"] for item in client.get(f"{API}/stats/dashboard").json()["top_restrooms"]
    }
    assert source["id"] not in restroom_ids
    target_detail = client.get(f"{API}/restrooms/{target['id']}").json()
    assert target_detail["inspection_count"] == 1
    assert target_detail["total_issue_count"] == 1

    # 4) 再次生成月度考核：已出的结果保持不动（不覆盖、不重算）
    again = client.post(
        f"{API}/assessments/generate",
        json={"period": period, "operator": "考核员"},
    ).json()
    frozen = next(
        item
        for item in client.get(f"{API}/assessments", params={"period": period}).json()
        if item["restroom_id"] == source["id"]
    )
    assert frozen["inspection_count"] == 1
    assert frozen["avg_score"] == 40.0
    assert frozen["grade"] == "不合格"
    assert frozen["restroom_code"] == source["code"]
    # 源点位的快照不是本次新建的
    assert all(item["restroom_id"] != source["id"] for item in again)

    # 承接方按当前归属得到当月考核（新生成，不影响源点位历史结果）
    target_snapshot = next(item for item in again if item["restroom_id"] == target["id"])
    assert target_snapshot["inspection_count"] == 1
    assert target_snapshot["avg_score"] == 40.0

    # 快照是独立数据，撤并不影响其留存
    with SessionLocal() as db:
        assert db.query(MonthlyAssessment).filter(
            MonthlyAssessment.restroom_id == source["id"],
            MonthlyAssessment.period == period,
        ).count() == 1


# ---------------------------------------------------------------------------
# 并发：合并执行窗口内正在提交的巡查必须落到确定的一方
# ---------------------------------------------------------------------------

def test_concurrent_inspections_during_merge_all_resolve_to_target(client, monkeypatch):
    from app.core.constants import INSPECTION_CHECK_ITEMS

    source = make_restroom(client, "并发撤并方")
    target = make_restroom(client, "并发承接方")
    adjustment = apply_merge(client, source["id"], target["id"])

    started = threading.Event()
    real_execute = adjustment_service._execute_merge

    def slow_execute(db, adj):
        # 让「点位已锁定、批量划转尚未开始」的窗口足够长，
        # 使并发巡查确实插入到合并执行过程中。
        started.set()
        time.sleep(0.5)
        return real_execute(db, adj)

    monkeypatch.setattr(adjustment_service, "_execute_merge", slow_execute)

    created_ids: list[int] = []
    errors: list[str] = []

    def submit_inspections():
        index = 0
        deadline = time.time() + 3
        while time.time() < deadline:
            index += 1
            for _ in range(30):
                db = SessionLocal()
                try:
                    inspection = inspection_service.create_inspection(
                        db,
                        InspectionCreate(
                            restroom_id=source["id"],
                            inspector=f"并发巡查{index}",
                            items=[
                                InspectionItem(name=name, score=9.0)
                                for name in INSPECTION_CHECK_ITEMS
                            ],
                        ),
                    )
                    created_ids.append(inspection.id)
                    break
                except OperationalError as exc:
                    db.rollback()
                    if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                        time.sleep(0.01)
                        continue
                    errors.append(str(exc))
                    break
                finally:
                    db.close()
            time.sleep(0.005)

    merger = threading.Thread(target=lambda: approve(client, adjustment["id"]))
    merger.start()
    assert started.wait(2)
    submit_inspections()
    merger.join(timeout=10)
    assert not merger.is_alive()
    assert not errors, errors
    assert created_ids, "并发窗口内应当成功提交过巡查"

    # 合并已完成；窗口内提交的巡查无一留在撤并方，全部确定地归属承接方
    with SessionLocal() as db:
        on_source = (
            db.query(Inspection)
            .filter(Inspection.id.in_(created_ids), Inspection.restroom_id == source["id"])
            .count()
        )
        on_target = (
            db.query(Inspection)
            .filter(Inspection.id.in_(created_ids), Inspection.restroom_id == target["id"])
            .count()
        )
        assert db.get(Restroom, source["id"]).status == "已撤并"
    assert on_source == 0
    assert on_target == len(created_ids)
