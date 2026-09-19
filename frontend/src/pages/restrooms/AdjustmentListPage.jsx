import { useState } from 'react';
import { Link } from 'react-router-dom';

import { adjustmentApi } from '../../api/adjustments.js';
import { assessmentApi } from '../../api/assessments.js';
import DataTable from '../../components/DataTable.jsx';
import Field from '../../components/Field.jsx';
import PageHeader from '../../components/PageHeader.jsx';
import Pagination from '../../components/Pagination.jsx';
import { StatusTag } from '../../components/Tags.jsx';
import { useToast } from '../../components/Toast.jsx';
import { useAsync } from '../../hooks/useAsync.js';
import { useListQuery } from '../../hooks/useListQuery.js';
import { formatDateTime } from '../../utils/format.js';
import AdjustmentDetailModal from './AdjustmentDetailModal.jsx';

const FILTERS = [
  { key: '', label: '全部单据' },
  { key: '待审批', label: '待审批' },
  { key: '已完成', label: '已完成' },
  { key: '已驳回', label: '已驳回' },
  { key: '执行失败', label: '执行失败' },
  { key: '已撤销', label: '已撤销' },
];

function adjustmentTone(status) {
  if (status === '待审批') return 'tag-warning';
  if (status === '已完成') return 'tag-success';
  if (status === '已驳回' || status === '执行失败') return 'tag-danger';
  return 'tag-neutral';
}

export function AdjustmentStatusPill({ status }) {
  return <span className={`tag ${adjustmentTone(status)}`}>{status}</span>;
}

function AssessmentPanel() {
  const toast = useToast();
  const [period, setPeriod] = useState(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  });
  const { data, loading, error, reload } = useAsync(() => assessmentApi.list(), []);

  const generate = async () => {
    if (!/^\d{4}-\d{2}$/.test(period)) {
      toast.error('月份格式应为 YYYY-MM');
      return;
    }
    try {
      const created = await assessmentApi.generate({ period, operator: '考核管理员' });
      toast.success(
        created.length ? `已生成 ${created.length} 个点位的月度考核快照` : '该月考核均已出具，结果保持不动',
      );
      reload();
    } catch (err) {
      toast.error(err.message);
    }
  };

  return (
    <section className="card">
      <div className="card-title">
        <h3>月度考核结果（冻结快照）</h3>
        <div className="inline">
          <Field label="考核月份">
            <input value={period} onChange={(event) => setPeriod(event.target.value)} placeholder="YYYY-MM" />
          </Field>
          <button type="button" className="btn btn-primary btn-sm" onClick={generate}>
            生成/补齐月度考核
          </button>
        </div>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        月度考核一经出具即冻结，后续公厕合并/拆分不会改动历史结果；实时看板统计按当前归属即时重算。
      </p>
      {error ? <div className="alert alert-error">{error.message}</div> : null}
      <DataTable
        loading={loading}
        rows={data || []}
        emptyText="暂无月度考核结果"
        columns={[
          { key: 'period', title: '考核月份' },
          { key: 'restroom_code', title: '点位编号' },
          { key: 'restroom_name', title: '点位名称', wrap: true },
          { key: 'inspection_count', title: '巡查次数' },
          { key: 'issue_count', title: '问题数' },
          { key: 'open_issue_count', title: '未闭环' },
          {
            key: 'avg_score',
            title: '月均得分',
            render: (row) => <strong>{Number(row.avg_score).toFixed(1)}</strong>,
          },
          { key: 'grade', title: '考核等级', render: (row) => <StatusTag status={row.grade} /> },
          { key: 'created_at', title: '出具时间', render: (row) => formatDateTime(row.created_at) },
        ]}
      />
    </section>
  );
}

export default function AdjustmentListPage() {
  const [statusFilter, setStatusFilter] = useState('待审批');
  const [detailId, setDetailId] = useState(null);
  const [traceCode, setTraceCode] = useState('');
  const [traceResult, setTraceResult] = useState(null);
  const toast = useToast();

  const list = useListQuery(
    (params) => adjustmentApi.list({ ...params, status: statusFilter || undefined }),
    {},
    10,
  );

  const trace = async () => {
    const code = traceCode.trim();
    if (!code) return;
    try {
      const rows = await adjustmentApi.traceByCode(code);
      setTraceResult(rows);
    } catch (err) {
      toast.error(err.message);
    }
  };

  return (
    <>
      <PageHeader
        title="合并拆分审批"
        description="公厕撤并、改造时的台账合并与拆分：申请审批、原子执行、原编号追溯"
      />
      <div className="content">
        <section className="card">
          <div className="filter-bar">
            {FILTERS.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`btn btn-sm${statusFilter === item.key ? ' btn-primary' : ''}`}
                onClick={() => setStatusFilter(item.key)}
              >
                {item.label}
              </button>
            ))}
            <span style={{ flex: 1 }} />
            <input
              value={traceCode}
              onChange={(event) => setTraceCode(event.target.value)}
              placeholder="输入原编号追溯，如 WC-0003"
              style={{ maxWidth: 240 }}
              onKeyDown={(event) => event.key === 'Enter' && trace()}
            />
            <button type="button" className="btn btn-sm" onClick={trace}>
              原编号追溯
            </button>
          </div>
          {traceResult ? (
            <div className="alert alert-info">
              {traceResult.length === 0 ? (
                `未找到编号 ${traceCode} 的撤并记录`
              ) : (
                <span>
                  原编号 <strong>{traceResult[0].original_code}</strong>（
                  {traceResult[0].original_name}）当前承接方：
                  {traceResult.map((row, index) => (
                    <span key={row.id}>
                      {index > 0 ? '；' : ''}
                      <Link to={`/restrooms/${row.current_restroom_id}`}>
                        {row.current_restroom?.code} {row.current_restroom?.name}
                      </Link>
                      （归入巡查 {row.moved_inspection_count} 条、问题 {row.moved_issue_count} 条，
                      {formatDateTime(row.created_at)}）
                    </span>
                  ))}
                </span>
              )}
            </div>
          ) : null}
        </section>

        <section className="card">
          <DataTable
            loading={list.loading}
            error={list.error}
            rows={list.items}
            emptyText="暂无合并/拆分审批单"
            columns={[
              { key: 'code', title: '调整单号' },
              {
                key: 'type',
                title: '类型',
                render: (row) => (
                  <span className={`tag ${row.type === '合并' ? 'tag-info' : 'tag-primary'}`}>{row.type}</span>
                ),
              },
              {
                key: 'source',
                title: '来源点位',
                render: (row) => (
                  <span>
                    {row.source_restroom?.code} {row.source_restroom?.name}
                  </span>
                ),
              },
              {
                key: 'target',
                title: '承接方 / 新点位',
                render: (row) =>
                  row.target_restroom ? (
                    <span>
                      {row.target_restroom.code} {row.target_restroom.name}
                    </span>
                  ) : (
                    <span className="muted">审批通过后创建</span>
                  ),
              },
              { key: 'reason', title: '依据', wrap: true },
              { key: 'applicant', title: '申请人' },
              { key: 'status', title: '状态', render: (row) => <AdjustmentStatusPill status={row.status} /> },
              { key: 'created_at', title: '提交时间', render: (row) => formatDateTime(row.created_at) },
              {
                key: 'actions',
                title: '操作',
                render: (row) => (
                  <button type="button" className="btn-link" onClick={() => setDetailId(row.id)}>
                    {row.status === '待审批' ? '审批' : '查看'}
                  </button>
                ),
              },
            ]}
          />
          <Pagination meta={list.meta} onPageChange={list.setPage} />
        </section>

        <AssessmentPanel />
      </div>

      {detailId ? (
        <AdjustmentDetailModal
          adjustmentId={detailId}
          onClose={() => setDetailId(null)}
          onChanged={() => {
            setDetailId(null);
            list.reload();
          }}
        />
      ) : null}
    </>
  );
}
