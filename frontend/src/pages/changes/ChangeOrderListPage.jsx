import { useState } from 'react';

import { changeOrderApi } from '../../api/changeOrders.js';
import DataTable from '../../components/DataTable.jsx';
import PageHeader from '../../components/PageHeader.jsx';
import { StatusTag } from '../../components/Tags.jsx';
import { useToast } from '../../components/Toast.jsx';
import { useAsync } from '../../hooks/useAsync.js';
import { formatDateTime } from '../../utils/format.js';
import ApprovalModal from './ApprovalModal.jsx';
import ChangeOrderDetailModal from './ChangeOrderDetailModal.jsx';

const TYPE_LABEL = { merge: '合并', split: '拆分' };
const STATUS_FILTERS = ['', '待审批', '已执行', '已驳回', '已撤销'];

export default function ChangeOrderListPage() {
  const toast = useToast();
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [approval, setApproval] = useState(null);
  const [detail, setDetail] = useState(null);

  const { data: orders, loading, error, reload } = useAsync(
    () =>
      changeOrderApi.list({
        status: statusFilter || undefined,
        type: typeFilter || undefined,
      }),
    [statusFilter, typeFilter],
  );

  const revoke = async (row) => {
    if (!window.confirm(`确认撤销变更单 ${row.code}？撤销后可重新发起。`)) return;
    try {
      await changeOrderApi.revoke(row.id);
      toast.success('已撤销');
      reload();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const partyName = (brief) => (brief ? `${brief.code} · ${brief.name}` : '-');

  return (
    <>
      <PageHeader
        title="合并 / 拆分审批"
        description="公厕撤并与拆分均需审批通过后方可执行，记录归属在单个事务内整体变更"
      />
      <div className="content">
        <section className="card">
          <div className="filter-bar">
            <div className="inline">
              <span className="muted">类型：</span>
              {['', 'merge', 'split'].map((value) => (
                <button
                  key={value || 'all'}
                  type="button"
                  className={`btn btn-sm${typeFilter === value ? ' btn-primary' : ''}`}
                  onClick={() => setTypeFilter(value)}
                >
                  {value === '' ? '全部' : TYPE_LABEL[value]}
                </button>
              ))}
            </div>
            <div className="inline">
              <span className="muted">状态：</span>
              {STATUS_FILTERS.map((value) => (
                <button
                  key={value || 'all'}
                  type="button"
                  className={`btn btn-sm${statusFilter === value ? ' btn-primary' : ''}`}
                  onClick={() => setStatusFilter(value)}
                >
                  {value || '全部'}
                </button>
              ))}
            </div>
          </div>
        </section>

        <section className="card">
          <DataTable
            loading={loading}
            error={error}
            rows={orders || []}
            emptyText="暂无变更单"
            columns={[
              { key: 'code', title: '变更单号', render: (row) => <button type="button" className="btn-link" onClick={() => setDetail(row)}>{row.code}</button> },
              { key: 'type', title: '类型', render: (row) => TYPE_LABEL[row.type] || row.type },
              { key: 'source', title: '被撤并 / 被拆分公厕', render: (row) => partyName(row.source_restroom) },
              {
                key: 'target',
                title: '承接方 / 新点位',
                render: (row) =>
                  row.type === 'merge'
                    ? partyName(row.target_restroom)
                    : partyName(row.new_restroom) || '审批后建档',
              },
              { key: 'applicant', title: '申请人' },
              { key: 'created_at', title: '提交时间', render: (row) => formatDateTime(row.created_at) },
              { key: 'status', title: '状态', render: (row) => <StatusTag status={row.status} /> },
              {
                key: 'actions',
                title: '操作',
                render: (row) => (
                  <div className="inline">
                    <button type="button" className="btn-link" onClick={() => setDetail(row)}>
                      详情
                    </button>
                    {row.status === '待审批' ? (
                      <>
                        <button
                          type="button"
                          className="btn-link"
                          onClick={() => setApproval({ order: row, mode: 'approve' })}
                        >
                          通过并执行
                        </button>
                        <button
                          type="button"
                          className="btn-link danger"
                          onClick={() => setApproval({ order: row, mode: 'reject' })}
                        >
                          驳回
                        </button>
                        <button type="button" className="btn-link danger" onClick={() => revoke(row)}>
                          撤销
                        </button>
                      </>
                    ) : null}
                  </div>
                ),
              },
            ]}
          />
        </section>
      </div>

      {approval ? (
        <ApprovalModal
          order={approval.order}
          mode={approval.mode}
          onClose={() => setApproval(null)}
          onDone={reload}
        />
      ) : null}
      {detail ? <ChangeOrderDetailModal order={detail} onClose={() => setDetail(null)} /> : null}
    </>
  );
}
