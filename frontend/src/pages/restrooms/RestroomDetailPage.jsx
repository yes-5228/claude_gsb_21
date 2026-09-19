import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { assessmentApi } from '../../api/assessments.js';
import { inspectionApi } from '../../api/inspections.js';
import { issueApi } from '../../api/issues.js';
import { restroomApi } from '../../api/restrooms.js';
import DataTable from '../../components/DataTable.jsx';
import DetailList from '../../components/DetailList.jsx';
import PageHeader from '../../components/PageHeader.jsx';
import Pagination from '../../components/Pagination.jsx';
import { ScorePill, SeverityTag, StatusTag } from '../../components/Tags.jsx';
import { useAsync } from '../../hooks/useAsync.js';
import { useListQuery } from '../../hooks/useListQuery.js';
import { formatDateTime } from '../../utils/format.js';
import IssueAssessmentModal, { AssessmentTag } from '../assessments/IssueAssessmentModal.jsx';
import MergeOrderModal from '../changes/MergeOrderModal.jsx';
import SplitOrderModal from '../changes/SplitOrderModal.jsx';
import RestroomFormModal from './RestroomFormModal.jsx';

const TABS = [
  { key: 'profile', label: '基础档案' },
  { key: 'inspections', label: '巡查记录' },
  { key: 'issues', label: '问题记录' },
  { key: 'assessments', label: '月度考核' },
];

export default function RestroomDetailPage() {
  const { restroomId } = useParams();
  const [tab, setTab] = useState('profile');
  const [showForm, setShowForm] = useState(false);
  const [showMerge, setShowMerge] = useState(false);
  const [showSplit, setShowSplit] = useState(false);
  const [showAssessment, setShowAssessment] = useState(false);

  const { data: restroom, loading, error, reload } = useAsync(
    () => restroomApi.detail(restroomId),
    [restroomId],
  );
  const inspections = useListQuery(
    (params) => inspectionApi.list({ ...params, restroom_id: restroomId }),
    {},
    5,
  );
  const issues = useListQuery(
    (params) => issueApi.list({ ...params, restroom_id: restroomId }),
    {},
    5,
  );
  const {
    data: assessments,
    reload: reloadAssessments,
  } = useAsync(() => assessmentApi.list({ restroom_id: restroomId }), [restroomId]);

  const isMerged = restroom?.status === '已撤并';

  return (
    <>
      <PageHeader
        title={restroom ? `${restroom.name}（${restroom.code}）` : '公厕详情'}
        description={restroom ? `${restroom.district} · ${restroom.address}` : '加载中…'}
        actions={
          <>
            <Link className="btn" to="/restrooms">
              返回列表
            </Link>
            <button type="button" className="btn btn-primary" onClick={() => setShowForm(true)}>
              编辑档案
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => setShowMerge(true)}
              disabled={isMerged}
              title={isMerged ? '该公厕已撤并' : ''}
            >
              发起合并
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => setShowSplit(true)}
              disabled={isMerged}
              title={isMerged ? '该公厕已撤并' : ''}
            >
              发起拆分
            </button>
          </>
        }
      />
      <div className="content">
        {error ? <div className="alert alert-error">{error.message}</div> : null}
        {loading && !restroom ? <div className="loading-block">加载中…</div> : null}

        {isMerged && restroom.merged_into ? (
          <div className="alert alert-warning">
            该公厕已于 {formatDateTime(restroom.merged_at)} 撤并，巡查、问题与考核记录已整体归到承接公厕
            <Link to={`/restrooms/${restroom.merged_into.id}`}>
              「{restroom.merged_into.name}」（{restroom.merged_into.code}）
            </Link>
            。本页保留原编号与台账信息用于追溯，不能再向该公厕提交巡查或问题。
          </div>
        ) : null}

        {restroom ? (
          <>
            <div className="stat-grid">
              <div className="stat-card">
                <div className="label">累计巡查</div>
                <div className="value">
                  {restroom.inspection_count}
                  <span className="unit">次</span>
                </div>
                <div className="foot">
                  最近巡查：{formatDateTime(restroom.latest_inspection_time)}
                </div>
              </div>
              <div className="stat-card is-info">
                <div className="label">巡查均分</div>
                <div className="value">
                  {restroom.avg_score != null ? restroom.avg_score.toFixed(1) : '-'}
                  <span className="unit">分</span>
                </div>
                <div className="foot">
                  最近得分：{restroom.latest_inspection_score ?? '-'}
                </div>
              </div>
              <div className={`stat-card${restroom.open_issue_count ? ' is-danger' : ''}`}>
                <div className="label">未闭环问题</div>
                <div className="value">
                  {restroom.open_issue_count}
                  <span className="unit">条</span>
                </div>
                <div className="foot">累计上报 {restroom.total_issue_count} 条</div>
              </div>
            </div>

            <div className="inline">
              {TABS.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className={`btn btn-sm${tab === item.key ? ' btn-primary' : ''}`}
                  onClick={() => setTab(item.key)}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {tab === 'profile' ? (
              <section className="card">
                <div className="card-title">
                  <h3>基础档案</h3>
                </div>
                <DetailList
                  items={[
                    { label: '公厕编号', value: restroom.code },
                    { label: '公厕名称', value: restroom.name },
                    { label: '所属区域', value: restroom.district },
                    { label: '详细地址', value: restroom.address },
                    { label: '公厕等级', value: restroom.grade },
                    { label: '开放状态', value: <StatusTag status={restroom.status} /> },
                    { label: '开放时间', value: restroom.open_hours },
                    { label: '保洁责任人', value: restroom.manager },
                    { label: '联系电话', value: restroom.manager_phone },
                    { label: '蹲位数量', value: `${restroom.stall_count} 个` },
                    { label: '洗手盆数量', value: `${restroom.basin_count} 个` },
                    { label: '无障碍设施', value: restroom.has_accessible ? '已配置' : '未配置' },
                    { label: '备注', value: restroom.remark || '无' },
                    { label: '建档时间', value: formatDateTime(restroom.created_at) },
                  ]}
                />
              </section>
            ) : null}

            {tab === 'inspections' ? (
              <section className="card">
                <div className="card-title">
                  <h3>巡查记录</h3>
                  <Link className="hint" to="/inspections">
                    前往巡查模块 →
                  </Link>
                </div>
                <DataTable
                  loading={inspections.loading}
                  error={inspections.error}
                  rows={inspections.items}
                  emptyText="该公厕暂无巡查记录"
                  columns={[
                    {
                      key: 'origin',
                      title: '来源',
                      render: (row) =>
                        row.origin_restroom_code ? (
                          <span className="tag tag-neutral" title="记录原始所属公厕">
                            原 {row.origin_restroom_code}
                          </span>
                        ) : (
                          <span className="muted">本厕</span>
                        ),
                    },
                    { key: 'inspect_time', title: '巡查时间', render: (row) => formatDateTime(row.inspect_time) },
                    { key: 'inspector', title: '巡查人' },
                    { key: 'shift', title: '班次' },
                    { key: 'score', title: '得分', render: (row) => <ScorePill score={row.score} /> },
                    { key: 'result', title: '结论', render: (row) => <StatusTag status={row.result} /> },
                    { key: 'remark', title: '备注', wrap: true, render: (row) => row.remark || '-' },
                  ]}
                />
                <Pagination meta={inspections.meta} onPageChange={inspections.setPage} />
              </section>
            ) : null}

            {tab === 'issues' ? (
              <section className="card">
                <div className="card-title">
                  <h3>问题记录</h3>
                  <Link className="hint" to="/issues">
                    前往整改模块 →
                  </Link>
                </div>
                <DataTable
                  loading={issues.loading}
                  error={issues.error}
                  rows={issues.items}
                  emptyText="该公厕暂无问题上报"
                  columns={[
                    { key: 'code', title: '编号' },
                    {
                      key: 'origin',
                      title: '来源',
                      render: (row) =>
                        row.origin_restroom_code ? (
                          <span className="tag tag-neutral" title="问题原始上报公厕">
                            原 {row.origin_restroom_code}
                          </span>
                        ) : (
                          <span className="muted">本厕</span>
                        ),
                    },
                    {
                      key: 'title',
                      title: '问题',
                      wrap: true,
                      render: (row) => <Link to={`/issues/${row.id}`}>{row.title}</Link>,
                    },
                    { key: 'category', title: '分类' },
                    { key: 'severity', title: '程度', render: (row) => <SeverityTag severity={row.severity} /> },
                    { key: 'status', title: '状态', render: (row) => <StatusTag status={row.status} /> },
                    { key: 'report_time', title: '上报时间', render: (row) => formatDateTime(row.report_time) },
                  ]}
                />
                <Pagination meta={issues.meta} onPageChange={issues.setPage} />
              </section>
            ) : null}

            {tab === 'assessments' ? (
              <section className="card">
                <div className="card-title">
                  <h3>月度考核结果</h3>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    onClick={() => setShowAssessment(true)}
                    disabled={isMerged}
                  >
                    出具月度考核
                  </button>
                </div>
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>考核月份</th>
                        <th>等次</th>
                        <th>巡查次数</th>
                        <th>均分</th>
                        <th>问题数</th>
                        <th>未闭环</th>
                        <th>出具人</th>
                        <th>出具时间</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(assessments || []).map((row) => (
                        <tr key={row.id}>
                          <td>{row.period}</td>
                          <td><AssessmentTag row={row} /></td>
                          <td>{row.inspection_count}</td>
                          <td>{Number(row.avg_score).toFixed(1)}</td>
                          <td>{row.issue_total}</td>
                          <td>{row.issue_open}</td>
                          <td>{row.issued_by || '-'}</td>
                          <td>{formatDateTime(row.issued_at)}</td>
                        </tr>
                      ))}
                      {assessments && assessments.length === 0 ? (
                        <tr>
                          <td colSpan={8} className="muted" style={{ textAlign: 'center', padding: 20 }}>
                            尚未出具月度考核
                          </td>
                        </tr>
                      ) : null}
                    </tbody>
                  </table>
                </div>
                <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>
                  考核结果出具后即冻结：拆分时已出具月份的结果保留在原公厕、不重算不迁移；合并时随记录归到承接方并保留原编号。
                </p>
              </section>
            ) : null}
          </>
        ) : null}
      </div>

      {showForm && restroom ? (
        <RestroomFormModal
          restroom={restroom}
          onClose={() => setShowForm(false)}
          onSaved={reload}
        />
      ) : null}
      {showMerge && restroom ? (
        <MergeOrderModal
          source={restroom}
          onClose={() => setShowMerge(false)}
          onCreated={() => reload()}
        />
      ) : null}
      {showSplit && restroom ? (
        <SplitOrderModal
          source={restroom}
          onClose={() => setShowSplit(false)}
          onCreated={() => reload()}
        />
      ) : null}
      {showAssessment && restroom ? (
        <IssueAssessmentModal
          restroomId={restroom.id}
          onClose={() => setShowAssessment(false)}
          onIssued={reloadAssessments}
        />
      ) : null}
    </>
  );
}
