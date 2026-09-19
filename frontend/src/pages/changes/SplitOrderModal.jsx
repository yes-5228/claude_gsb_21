import { useEffect, useMemo, useState } from 'react';

import { changeOrderApi } from '../../api/changeOrders.js';
import Field from '../../components/Field.jsx';
import Modal from '../../components/Modal.jsx';
import { StatusTag } from '../../components/Tags.jsx';
import { useToast } from '../../components/Toast.jsx';
import { useDictionaries } from '../../hooks/useDictionaries.js';
import { useAsync } from '../../hooks/useAsync.js';

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

export default function SplitOrderModal({ source, onClose, onCreated }) {
  const toast = useToast();
  const { dictionaries } = useDictionaries();
  const [form, setForm] = useState({ ...EMPTY_NEW, district: source.district || '' });
  // issue_id -> 'new' | 'source'，默认全部划归新点位，需用户逐条确认
  const [assign, setAssign] = useState({});
  const [reason, setReason] = useState('');
  const [applicant, setApplicant] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const { data: preview } = useAsync(
    () => changeOrderApi.preview({ type: 'split', source_restroom_id: source.id }),
    [source.id],
  );
  const openIssues = useMemo(() => preview?.open_issues || [], [preview]);

  useEffect(() => {
    setAssign((prev) => {
      const next = { ...prev };
      openIssues.forEach((item) => {
        if (next[item.issue_id] === undefined) next[item.issue_id] = 'new';
      });
      return next;
    });
  }, [openIssues]);

  const setValue = (key) => (event) => {
    const target = event.target;
    const value =
      target.type === 'checkbox'
        ? target.checked
        : target.type === 'number'
          ? Number(target.value)
          : target.value;
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const submit = async (event) => {
    event.preventDefault();
    setError(null);
    if (!form.name.trim() || !form.district.trim()) {
      setError('新点位名称与所属区域为必填项');
      return;
    }
    if (reason.trim().length < 5) {
      setError('请填写变更依据（至少 5 个字）');
      return;
    }
    const issueAssignments = openIssues.map((item) => ({
      issue_id: item.issue_id,
      destination: assign[item.issue_id] || 'source',
    }));
    setSaving(true);
    try {
      const order = await changeOrderApi.createSplit({
        source_restroom_id: source.id,
        new_restroom: { ...form },
        issue_assignments: issueAssignments,
        reason: reason.trim(),
        applicant: applicant.trim(),
      });
      toast.success(`拆分申请 ${order.code} 已提交，等待审批`);
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
      title={`公厕拆分 - ${source.code} ${source.name}`}
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
      <form id="split-form" onSubmit={submit}>
        <div className="form-grid">
          <Field label="原公厕" full>
            <input value={`${source.code} · ${source.name}（${source.district}）`} disabled />
          </Field>
        </div>

        <div className="card-title" style={{ marginTop: 12 }}>
          <h3>新点位档案</h3>
        </div>
        <div className="form-grid">
          <Field label="新点位名称 *">
            <input value={form.name} onChange={setValue('name')} placeholder="如：体育中心东公厕" />
          </Field>
          <Field label="所属区域 *">
            <input value={form.district} onChange={setValue('district')} />
          </Field>
          <Field label="公厕等级">
            <select value={form.grade} onChange={setValue('grade')}>
              {(dictionaries?.restroom_grade || ['一类', '二类', '三类']).map((item) => (
                <option key={item}>{item}</option>
              ))}
            </select>
          </Field>
          <Field label="开放状态">
            <select value={form.status} onChange={setValue('status')}>
              {(dictionaries?.restroom_status || ['正常开放', '维修中', '暂停使用'])
                .filter((item) => item !== '已撤并')
                .map((item) => (
                  <option key={item}>{item}</option>
                ))}
            </select>
          </Field>
          <Field label="保洁责任人">
            <input value={form.manager} onChange={setValue('manager')} />
          </Field>
          <Field label="联系电话">
            <input value={form.manager_phone} onChange={setValue('manager_phone')} />
          </Field>
          <Field label="蹲位数量">
            <input type="number" min="0" value={form.stall_count} onChange={setValue('stall_count')} />
          </Field>
          <Field label="洗手盆数量">
            <input type="number" min="0" value={form.basin_count} onChange={setValue('basin_count')} />
          </Field>
          <Field label="详细地址" full>
            <input value={form.address} onChange={setValue('address')} />
          </Field>
        </div>

        <div className="card-title" style={{ marginTop: 12 }}>
          <h3>未闭环问题划归（{openIssues.length} 条）</h3>
        </div>
        {openIssues.length === 0 ? (
          <div className="alert alert-info">该公厕当前没有未闭环问题，拆分后仅新增点位，无在办任务需要划转。</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>问题编号</th>
                  <th>问题</th>
                  <th>状态</th>
                  <th>责任人</th>
                  <th style={{ width: 240 }}>划归去向</th>
                </tr>
              </thead>
              <tbody>
                {openIssues.map((item) => (
                  <tr key={item.issue_id}>
                    <td>{item.code}</td>
                    <td>{item.title}</td>
                    <td>
                      <StatusTag status={item.status} />
                    </td>
                    <td>{item.assignee || '-'}</td>
                    <td>
                      <select
                        value={assign[item.issue_id] || 'new'}
                        onChange={(e) =>
                          setAssign((prev) => ({ ...prev, [item.issue_id]: e.target.value }))
                        }
                      >
                        <option value="new">划归新点位</option>
                        <option value="source">留在原公厕</option>
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted" style={{ fontSize: 12, margin: '8px 0' }}>
          历史巡查、已闭环问题与已出具的月度考核结果不随拆分迁移，月度考核仍保留在原公厕且不重算。
        </p>

        <div className="form-grid">
          <Field label="申请人">
            <input value={applicant} onChange={(e) => setApplicant(e.target.value)} placeholder="填报人" />
          </Field>
          <Field label="变更依据 / 原因说明 *" full>
            <textarea
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="如：区域改造需拆分为两座独立点位，附现场核查与批复文件"
            />
          </Field>
        </div>
      </form>
    </Modal>
  );
}
