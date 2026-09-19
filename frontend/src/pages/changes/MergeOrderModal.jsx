import { useEffect, useMemo, useState } from 'react';

import { changeOrderApi } from '../../api/changeOrders.js';
import { metaApi } from '../../api/meta.js';
import Field from '../../components/Field.jsx';
import Modal from '../../components/Modal.jsx';
import { useToast } from '../../components/Toast.jsx';
import { useAsync } from '../../hooks/useAsync.js';

export default function MergeOrderModal({ source, onClose, onCreated }) {
  const toast = useToast();
  const [targetId, setTargetId] = useState('');
  const [reason, setReason] = useState('');
  const [applicant, setApplicant] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const { data: options } = useAsync(() => metaApi.restroomOptions(), []);
  const targets = useMemo(
    () => (options || []).filter((item) => item.id !== source.id),
    [options, source.id],
  );

  const { data: preview, reload: reloadPreview } = useAsync(
    () =>
      changeOrderApi.preview({
        type: 'merge',
        source_restroom_id: source.id,
        target_restroom_id: targetId,
      }),
    [targetId],
    { immediate: false },
  );

  useEffect(() => {
    if (targetId) reloadPreview();
  }, [targetId, reloadPreview]);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    if (!targetId) {
      setError('请选择承接公厕');
      return;
    }
    if (reason.trim().length < 5) {
      setError('请填写变更依据（至少 5 个字）');
      return;
    }
    setSaving(true);
    try {
      const order = await changeOrderApi.createMerge({
        source_restroom_id: source.id,
        target_restroom_id: Number(targetId),
        reason: reason.trim(),
        applicant: applicant.trim(),
      });
      toast.success(`合并申请 ${order.code} 已提交，等待审批`);
      onCreated?.(order);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`公厕合并 - ${source.code} ${source.name}`}
      onClose={onClose}
      width={720}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            取消
          </button>
          <button type="submit" form="merge-form" className="btn btn-primary" disabled={saving}>
            {saving ? '提交中…' : '提交合并申请'}
          </button>
        </>
      }
    >
      {error ? <div className="alert alert-error">{error}</div> : null}
      <form id="merge-form" className="form-grid" onSubmit={submit}>
        <Field label="被撤并公厕" full>
          <input value={`${source.code} · ${source.name}（${source.district}）`} disabled />
        </Field>
        <Field label="承接公厕 *" full>
          <select value={targetId} onChange={(e) => setTargetId(e.target.value)}>
            <option value="">请选择承接公厕…</option>
            {targets.map((item) => (
              <option key={item.id} value={item.id}>
                {item.code} · {item.name}（{item.district}）
              </option>
            ))}
          </select>
        </Field>

        {preview && targetId ? (
          <div className="field grow">
            <label>变更影响面预览</label>
            <div className="alert alert-info">
              审批通过后，原公厕将标记为「已撤并」，其
              <b> {preview.inspection_count} </b> 条巡查、
              <b> {preview.issue_open_count + preview.issue_closed_count} </b> 条问题
              （未闭环 {preview.issue_open_count} 条、已闭环 {preview.issue_closed_count} 条）、
              <b> {preview.assessment_count} </b> 份月度考核将整体归到承接方，并保留原编号备查。
            </div>
          </div>
        ) : null}

        <Field label="申请人">
          <input value={applicant} onChange={(e) => setApplicant(e.target.value)} placeholder="填报人" />
        </Field>
        <Field label="变更依据 / 原因说明 *" full>
          <textarea
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="如：两厕物理连通、管养主体合并，附上级批复或现场核查情况"
          />
        </Field>
      </form>
    </Modal>
  );
}
