import { useEffect, useState } from 'react';

import { adjustmentApi } from '../../api/adjustments.js';
import Field from '../../components/Field.jsx';
import Modal from '../../components/Modal.jsx';
import { SeverityTag, StatusTag } from '../../components/Tags.jsx';
import { useToast } from '../../components/Toast.jsx';
import { useDictionaries } from '../../hooks/useDictionaries.js';

const EMPTY_NEW = {
  name: '',
  district: '',
  address: '',
  grade: '二类',
  status: '正常开放',
  manager: '',
  manager_phone: '',
  open_hours: '06:00-22:00',
  stall_count: 0,
  basin_count: 0,
  has_accessible: true,
};

/**
 * 拆分申请弹窗：从 restroom 拆出新点位。
 * 未闭环问题/在办任务逐条勾选划归新点位；历史巡查与已闭环记录留在原点位。
 */
export default function SplitApplyModal({ restroom, onClose, onSubmitted }) {
  const { dictionaries } = useDictionaries();
  const toast = useToast();
  const [form, setForm] = useState({ reason: '', applicant: '' });
  const [next, setNext] = useState(EMPTY_NEW);
  const [issues, setIssues] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    adjustmentApi
      .movableIssues(restroom.id)
      .then(setIssues)
      .catch((err) => setError(err.message));
  }, [restroom.id]);

  const toggle = (id) => {
    setSelected((prev) => {
      const clone = new Set(prev);
      if (clone.has(id)) clone.delete(id);
      else clone.add(id);
      return clone;
    });
  };

  const setNextValue = (key) => (event) => {
    const target = event.target;
    const value =
      target.type === 'checkbox'
        ? target.checked
        : target.type === 'number'
          ? Number(target.value)
          : target.value;
    setNext((prev) => ({ ...prev, [key]: value }));
  };

  const submit = async (event) => {
    event.preventDefault();
    if (!next.name.trim() || !next.district.trim()) {
      setError('新点位名称与所属区域为必填项');
      return;
    }
    if (form.reason.trim().length < 5) {
      setError('请填写拆分依据与说明（至少 5 个字）');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await adjustmentApi.applySplit({
        source_restroom_id: restroom.id,
        reason: form.reason.trim(),
        applicant: form.applicant.trim(),
        new_restroom: next,
        move_issue_ids: [...selected],
      });
      toast.success('拆分申请已提交，等待审批');
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
      title={`拆出新点位 - 自 ${restroom.name}（${restroom.code}）`}
      onClose={onClose}
      width={860}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            取消
          </button>
          <button type="submit" form="split-form" className="btn btn-primary" disabled={saving}>
            {saving ? '提交中…' : '提交拆分申请'}
          </button>
        </>
      }
    >
      {error ? <div className="alert alert-error">{error}</div> : null}
      <div className="alert alert-warning">
        审批通过后创建新点位；勾选的未闭环问题/在办任务将明确划归新点位并留划转轨迹，
        历史巡查与已闭环记录保留在原点位；月度考核已出结果不变。
      </div>
      <form id="split-form" onSubmit={submit}>
        <div className="card-title">
          <h3>新点位档案</h3>
        </div>
        <div className="form-grid">
          <Field label="新点位名称 *">
            <input value={next.name} onChange={setNextValue('name')} placeholder="如：滨江公园东侧公共厕所" />
          </Field>
          <Field label="所属区域 *">
            <input value={next.district} onChange={setNextValue('district')} />
          </Field>
          <Field label="公厕等级">
            <select value={next.grade} onChange={setNextValue('grade')}>
              {(dictionaries?.restroom_grade || ['一类', '二类', '三类']).map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </Field>
          <Field label="责任人">
            <input value={next.manager} onChange={setNextValue('manager')} />
          </Field>
          <Field label="联系电话">
            <input value={next.manager_phone} onChange={setNextValue('manager_phone')} />
          </Field>
          <Field label="开放时间">
            <input value={next.open_hours} onChange={setNextValue('open_hours')} />
          </Field>
          <Field label="蹲位数量">
            <input type="number" min="0" value={next.stall_count} onChange={setNextValue('stall_count')} />
          </Field>
          <Field label="洗手盆数量">
            <input type="number" min="0" value={next.basin_count} onChange={setNextValue('basin_count')} />
          </Field>
          <Field label="无障碍设施">
            <label className="checkbox-row">
              <input type="checkbox" checked={next.has_accessible} onChange={setNextValue('has_accessible')} />
              已配置
            </label>
          </Field>
          <Field label="详细地址" full>
            <input value={next.address} onChange={setNextValue('address')} />
          </Field>
        </div>

        <div className="card-title">
          <h3>划归新点位的未闭环问题 / 在办任务</h3>
          <div className="inline">
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setSelected(new Set(issues.map((item) => item.id)))}
            >
              全选
            </button>
            <button type="button" className="btn btn-sm" onClick={() => setSelected(new Set())}>
              清空
            </button>
          </div>
        </div>
        {issues.length === 0 ? (
          <div className="empty-block">该点位当前没有未闭环问题/在办任务，拆分后新点位从空白开始积累。</div>
        ) : (
          <div className="check-grid">
            {issues.map((issue) => (
              <label className={`check-item${selected.has(issue.id) ? ' is-low' : ''}`} key={issue.id}>
                <div className="name" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <input type="checkbox" checked={selected.has(issue.id)} onChange={() => toggle(issue.id)} />
                  <span>{issue.code}</span>
                  <StatusTag status={issue.status} />
                  <SeverityTag severity={issue.severity} />
                </div>
                <div style={{ marginTop: 4 }}>{issue.title}</div>
                <div className="muted" style={{ marginTop: 2, fontSize: 12 }}>
                  责任人：{issue.assignee || '未派单'}
                </div>
              </label>
            ))}
          </div>
        )}

        <div className="form-grid" style={{ marginTop: 12 }}>
          <Field label="拆分依据与说明 *" full hint="如：管养边界调整、物理隔断改造、批复文件等">
            <textarea
              rows={3}
              value={form.reason}
              onChange={(event) => setForm((prev) => ({ ...prev, reason: event.target.value }))}
              placeholder="说明拆分的事实依据、批复文件或现场情况"
            />
          </Field>
          <Field label="申请人">
            <input
              value={form.applicant}
              onChange={(event) => setForm((prev) => ({ ...prev, applicant: event.target.value }))}
              placeholder="申请人姓名"
            />
          </Field>
        </div>
      </form>
    </Modal>
  );
}
