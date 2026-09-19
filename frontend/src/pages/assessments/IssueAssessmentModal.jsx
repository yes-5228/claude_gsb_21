import { useState } from 'react';

import { assessmentApi } from '../../api/assessments.js';
import Field from '../../components/Field.jsx';
import Modal from '../../components/Modal.jsx';
import { GradeTag } from '../../components/Tags.jsx';
import { useToast } from '../../components/Toast.jsx';

function defaultPeriod() {
  const now = new Date();
  let year = now.getFullYear();
  let month = now.getMonth(); // 上月
  if (month === 0) {
    year -= 1;
    month = 12;
  }
  return `${year}-${String(month).padStart(2, '0')}`;
}

export default function IssueAssessmentModal({ restroomId, onClose, onIssued }) {
  const toast = useToast();
  const [period, setPeriod] = useState(defaultPeriod());
  const [issuedBy, setIssuedBy] = useState('');
  const [remark, setRemark] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      const row = await assessmentApi.issue(restroomId, {
        period,
        issued_by: issuedBy.trim(),
        remark: remark.trim() || null,
      });
      toast.success(`${period} 月度考核已出具并冻结（${row.grade}）`);
      onIssued?.(row);
      onClose();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="出具月度考核"
      onClose={onClose}
      width={520}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            取消
          </button>
          <button type="submit" form="assessment-form" className="btn btn-primary" disabled={saving}>
            {saving ? '出具中…' : '出具并冻结'}
          </button>
        </>
      }
    >
      {error ? <div className="alert alert-error">{error}</div> : null}
      <div className="alert alert-info" style={{ marginBottom: 12 }}>
        考核结果按当前记录归属汇总一次后即冻结；此后公厕即使被拆分，已出具月份的结果也不重算、不迁移。
      </div>
      <form id="assessment-form" className="form-grid" onSubmit={submit}>
        <Field label="考核月份 *" hint="格式 YYYY-MM，默认上一个自然月">
          <input value={period} onChange={(e) => setPeriod(e.target.value)} placeholder="2026-08" />
        </Field>
        <Field label="出具人">
          <input value={issuedBy} onChange={(e) => setIssuedBy(e.target.value)} />
        </Field>
        <Field label="考核说明" full>
          <textarea rows={2} value={remark} onChange={(e) => setRemark(e.target.value)} />
        </Field>
      </form>
    </Modal>
  );
}

export function AssessmentTag({ row }) {
  return (
    <span className="inline">
      <GradeTag grade={row.grade} />
      {row.origin_restroom_code ? (
        <span className="tag tag-neutral" title="考核原始来源公厕">
          原 {row.origin_restroom_code}
        </span>
      ) : null}
    </span>
  );
}
