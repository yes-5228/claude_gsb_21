import { useState } from 'react';

import { adjustmentApi } from '../../api/adjustments.js';
import DetailList from '../../components/DetailList.jsx';
import Modal from '../../components/Modal.jsx';
import { SeverityTag, StatusTag } from '../../components/Tags.jsx';
import Timeline from '../../components/Timeline.jsx';
import { useToast } from '../../components/Toast.jsx';
import { useAsync } from '../../hooks/useAsync.js';
import { formatDateTime } from '../../utils/format.js';
import { AdjustmentStatusPill } from './AdjustmentListPage.jsx';

export default function AdjustmentDetailModal({ adjustmentId, onClose, onChanged }) {
  const toast = useToast();
  const [approver, setApprover] = useState('');
  const [remark, setRemark] = useState('');
  const [saving, setSaving] = useState(false);
  const { data: adjustment, loading, error, reload } = useAsync(
    () => adjustmentApi.detail(adjustmentId),
    [adjustmentId],
  );

  const decide = async (action) => {
    if (!approver.trim()) {
      toast.error('请填写审批人');
      return;
    }
    const word = action === 'approve' ? '通过' : '驳回';
    if (
      action === 'approve' &&
      !window.confirm(
        '审批通过将立即原子执行归属变更：记录整体划转、原编号留痕；中途异常会整体回滚。确认通过？',
      )
    ) {
      return;
    }
    if (action === 'reject' && !remark.trim() && !window.confirm('驳回未填写意见，确认驳回？')) {
      return;
    }
    setSaving(true);
    try {
      const result = await adjustmentApi[action](adjustmentId, {
        approver: approver.trim(),
        remark: remark.trim() || null,
      });
      if (result.status === '执行失败') {
        toast.error('执行失败，归属变更已整体回滚，未产生任何数据变更');
        reload();
      } else {
        toast.success(`已${word}${action === 'approve' ? '并执行' : ''}`);
        onChanged();
      }
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const cancelApply = async () => {
    if (!approver.trim()) {
      toast.error('请填写操作人以撤销申请');
      return;
    }
    setSaving(true);
    try {
      await adjustmentApi.cancel(adjustmentId, { approver: approver.trim(), remark: null });
      toast.success('申请已撤销');
      onChanged();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  };

  const footer =
    adjustment?.status === '待审批' ? (
      <>
        <button type="button" className="btn" onClick={onClose} disabled={saving}>
          关闭
        </button>
        <button type="button" className="btn" onClick={cancelApply} disabled={saving}>
          撤销申请
        </button>
        <button
          type="button"
          className="btn btn-danger"
          onClick={() => decide('reject')}
          disabled={saving}
        >
          {saving ? '处理中…' : '驳回'}
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => decide('approve')}
          disabled={saving}
        >
          {saving ? '执行中…' : '审批通过并执行'}
        </button>
      </>
    ) : (
      <button type="button" className="btn btn-primary" onClick={onClose}>
        关闭
      </button>
    );

  return (
    <Modal title={adjustment ? `调整单 ${adjustment.code}` : '调整单详情'} onClose={onClose} width={860} footer={footer}>
      {error ? <div className="alert alert-error">{error.message}</div> : null}
      {loading ? <div className="loading-block">加载中…</div> : null}
      {adjustment ? (
        <>
          <div className="inline" style={{ marginBottom: 12 }}>
            <span className={`tag ${adjustment.type === '合并' ? 'tag-info' : 'tag-primary'}`}>
              {adjustment.type}
            </span>
            <AdjustmentStatusPill status={adjustment.status} />
            <span className="muted">提交于 {formatDateTime(adjustment.created_at)}</span>
          </div>

          {adjustment.fail_reason ? (
            <div className="alert alert-error">
              <strong>执行失败：</strong>
              {adjustment.fail_reason}
            </div>
          ) : null}

          <DetailList
            items={[
              {
                label: adjustment.type === '合并' ? '被撤并点位' : '原点位',
                value: `${adjustment.source_restroom?.code} ${adjustment.source_restroom?.name}`,
              },
              {
                label: adjustment.type === '合并' ? '承接方' : '拆出的新点位',
                value: adjustment.target_restroom
                  ? `${adjustment.target_restroom.code} ${adjustment.target_restroom.name}`
                  : '审批通过后创建',
              },
              { label: '申请人', value: adjustment.applicant || '-' },
              { label: '审批人', value: adjustment.approver || '-' },
              { label: '审批时间', value: formatDateTime(adjustment.approved_at) },
              { label: '执行时间', value: formatDateTime(adjustment.executed_at) },
              { label: '调整依据', value: adjustment.reason },
              { label: '审批意见', value: adjustment.approval_remark || '-' },
            ]}
          />

          <div className="card-title">
            <h3>
              {adjustment.type === '合并'
                ? `来源点位当前记录（执行后整体归到承接方）：巡查 ${adjustment.source_inspection_count} 条、问题 ${adjustment.source_issue_count} 条（未闭环 ${adjustment.source_open_issue_count} 条）`
                : `划归清单：${adjustment.move_issue_ids.length} 条未闭环问题/在办任务划归新点位`}
            </h3>
          </div>

          {adjustment.type === '拆分' && adjustment.status === '待审批' ? (
            adjustment.movable_issues.length === 0 ? (
              <div className="empty-block">原点位当前没有未闭环问题/在办任务</div>
            ) : (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>划归</th>
                      <th>编号</th>
                      <th>问题</th>
                      <th>程度</th>
                      <th>状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    {adjustment.movable_issues.map((issue) => (
                      <tr key={issue.id}>
                        <td>{adjustment.move_issue_ids.includes(issue.id) ? '✅ 新点位' : '➖ 留原点位'}</td>
                        <td>{issue.code}</td>
                        <td>{issue.title}</td>
                        <td>
                          <SeverityTag severity={issue.severity} />
                        </td>
                        <td>
                          <StatusTag status={issue.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          ) : null}

          <div className="card-title">
            <h3>审批 / 执行轨迹</h3>
          </div>
          <Timeline records={adjustment.logs} />

          {adjustment.status === '待审批' ? (
            <div className="form-grid" style={{ marginTop: 12 }}>
              <div className="field">
                <label>审批人 *</label>
                <input value={approver} onChange={(event) => setApprover(event.target.value)} placeholder="审批人姓名" />
              </div>
              <div className="field grow">
                <label>审批意见</label>
                <input value={remark} onChange={(event) => setRemark(event.target.value)} placeholder="通过或驳回意见" />
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </Modal>
  );
}
