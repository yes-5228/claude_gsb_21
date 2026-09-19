import { useState } from 'react';

import { changeOrderApi } from '../../api/changeOrders.js';
import DetailList from '../../components/DetailList.jsx';
import Field from '../../components/Field.jsx';
import Modal from '../../components/Modal.jsx';
import { useToast } from '../../components/Toast.jsx';

/**
 * 审批弹窗：mode = 'approve' | 'reject'。
 * 「通过并执行」会提示这是原子操作：成功才整体生效，失败完全回滚。
 */
export default function ApprovalModal({ order, mode, onClose, onDone }) {
  const toast = useToast();
  const [approver, setApprover] = useState('');
  const [remark, setRemark] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const isApprove = mode === 'approve';

  const submit = async (event) => {
    event.preventDefault();
    if (!approver.trim()) {
      setError('请填写审批人');
      return;
    }
    if (!isApprove && !remark.trim()) {
      setError('驳回时必须填写审批意见');
      return;
    }
    if (
      isApprove &&
      !window.confirm(
        '审批通过将立即执行归属变更。该操作在单个事务内整体完成：成功全部生效，失败完全回滚，不会出现记录只迁移一半。确认执行？',
      )
    ) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = { approver: approver.trim(), remark: remark.trim() || null };
      const updated = isApprove
        ? await changeOrderApi.approve(order.id, payload)
        : await changeOrderApi.reject(order.id, payload);
      toast.success(isApprove ? '已审批通过并执行' : '已驳回');
      onDone?.(updated);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const sourceName = order.source_restroom
    ? `${order.source_restroom.code} · ${order.source_restroom.name}`
    : `公厕 ${order.source_restroom_id}`;
  const targetName = order.target_restroom
    ? `${order.target_restroom.code} · ${order.target_restroom.name}`
    : order.new_restroom
      ? `新点位 ${order.new_restroom.code} · ${order.new_restroom.name}`
      : '-';

  return (
    <Modal
      title={isApprove ? '审批通过并执行' : '审批驳回'}
      onClose={onClose}
      width={560}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            取消
          </button>
          <button
            type="submit"
            form="approval-form"
            className={`btn ${isApprove ? 'btn-primary' : 'btn-danger'}`}
            disabled={saving}
          >
            {saving ? '处理中…' : isApprove ? '确认通过并执行' : '确认驳回'}
          </button>
        </>
      }
    >
      {error ? <div className="alert alert-error">{error}</div> : null}
      <form id="approval-form" onSubmit={submit}>
        <div style={{ marginBottom: 12 }}>
          <DetailList
            items={[
              { label: '变更单', value: order.code },
              { label: '类型', value: order.type === 'merge' ? '合并' : '拆分' },
              {
                label: order.type === 'merge' ? '被撤并公厕' : '被拆分公厕',
                value: sourceName,
              },
              { label: order.type === 'merge' ? '承接公厕' : '新点位', value: targetName },
              { label: '变更依据', value: order.reason },
            ]}
          />
        </div>
        {isApprove ? (
          <div className="alert alert-info" style={{ marginBottom: 12 }}>
            通过后记录归属、公厕状态一次性整体更新；执行中途若失败将完全回滚，变更单回到「待审批」。
          </div>
        ) : null}
        <div className="form-grid">
          <Field label="审批人 *">
            <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="审批人姓名" />
          </Field>
          <Field label={isApprove ? '审批意见' : '驳回原因 *'} full>
            <textarea
              rows={3}
              value={remark}
              onChange={(e) => setRemark(e.target.value)}
              placeholder={isApprove ? '可留空' : '请说明驳回原因'}
            />
          </Field>
        </div>
      </form>
    </Modal>
  );
}
