import { useEffect, useState } from 'react';

import { adjustmentApi } from '../../api/adjustments.js';
import { metaApi } from '../../api/meta.js';
import Field from '../../components/Field.jsx';
import Modal from '../../components/Modal.jsx';
import { useToast } from '../../components/Toast.jsx';

/**
 * 合并申请弹窗：把 restroom（被撤并方）并入选择的承接方。
 * 审批通过后该点位全部巡查/问题记录整体归到承接方，原编号保留可追溯。
 */
export default function MergeApplyModal({ restroom, onClose, onSubmitted }) {
  const toast = useToast();
  const [options, setOptions] = useState([]);
  const [form, setForm] = useState({
    target_restroom_id: '',
    reason: '',
    applicant: '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    metaApi
      .restroomOptions()
      .then((rows) => setOptions(rows.filter((row) => row.id !== restroom.id)))
      .catch((err) => setError(err.message));
  }, [restroom.id]);

  const target = options.find((row) => String(row.id) === String(form.target_restroom_id));

  const submit = async (event) => {
    event.preventDefault();
    if (!form.target_restroom_id) {
      setError('请选择承接公厕');
      return;
    }
    if (form.reason.trim().length < 5) {
      setError('请填写合并依据与说明（至少 5 个字）');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await adjustmentApi.applyMerge({
        source_restroom_id: restroom.id,
        target_restroom_id: Number(form.target_restroom_id),
        reason: form.reason.trim(),
        applicant: form.applicant.trim(),
      });
      toast.success('合并申请已提交，等待审批');
      onSubmitted();
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={`合并撤并 - ${restroom.name}（${restroom.code}）`}
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
      <div className="alert alert-warning">
        审批通过后，「{restroom.name}」将被撤并，其全部历史巡查
        {restroom.inspection_count ?? 0} 条、问题记录
        {restroom.total_issue_count ?? 0} 条（含已闭环及整改轨迹）整体归到承接方，
        原编号保留用于追溯；操作要么整体成立，要么完全不动。
      </div>
      <form id="merge-form" className="form-grid" onSubmit={submit}>
        <Field label="被撤并点位" full>
          <input value={`${restroom.code} ${restroom.name}（${restroom.district}）`} disabled />
        </Field>
        <Field label="承接公厕 *" full>
          <select
            value={form.target_restroom_id}
            onChange={(event) => setForm((prev) => ({ ...prev, target_restroom_id: event.target.value }))}
          >
            <option value="">请选择承接公厕</option>
            {options.map((option) => (
              <option key={option.id} value={option.id}>
                {option.code} {option.name}（{option.district}）
              </option>
            ))}
          </select>
        </Field>
        {target ? (
          <Field label="承接方确认" full>
            <div className="alert alert-info" style={{ marginBottom: 0 }}>
              合并后记录归属：{target.code} {target.name}
            </div>
          </Field>
        ) : null}
        <Field label="合并依据与说明 *" full hint="如：两点位距离、管网/管养边界调整、批复文件等">
          <textarea
            rows={3}
            value={form.reason}
            onChange={(event) => setForm((prev) => ({ ...prev, reason: event.target.value }))}
            placeholder="说明撤并的事实依据、批复文件或现场情况"
          />
        </Field>
        <Field label="申请人">
          <input
            value={form.applicant}
            onChange={(event) => setForm((prev) => ({ ...prev, applicant: event.target.value }))}
            placeholder="申请人姓名"
          />
        </Field>
      </form>
    </Modal>
  );
}
