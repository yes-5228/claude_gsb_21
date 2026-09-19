import DetailList from '../../components/DetailList.jsx';
import Modal from '../../components/Modal.jsx';
import { StatusTag } from '../../components/Tags.jsx';
import { formatDateTime } from '../../utils/format.js';

const TYPE_LABEL = { merge: '合并', split: '拆分' };

function SnapshotBlock({ order }) {
  const snap = order.result_snapshot;
  if (!snap) {
    return <div className="alert alert-info">尚未执行，审批通过后在此展示归属变更结果。</div>;
  }
  if (order.type === 'merge') {
    return (
      <div className="alert alert-success">
        已于 {formatDateTime(order.approved_at)} 执行：{snap.moved_inspection_count} 条巡查、
        {snap.moved_issue_count} 条问题、{snap.moved_assessment_count} 份月度考核由
        {snap.source_restroom_code} 整体归并到 {snap.target_restroom_code}，原编号已保留。
      </div>
    );
  }
  return (
    <div className="alert alert-success">
      已于 {formatDateTime(order.approved_at)} 执行：新点位 {snap.new_restroom_code} 建档完成，
      划归在办问题 {snap.moved_issue_count} 条、留在原公厕 {snap.retained_issue_count} 条；
      历史巡查与已出具的 {snap.frozen_assessment_count} 份月度考核保持不动。
    </div>
  );
}

export default function ChangeOrderDetailModal({ order, onClose }) {
  const targetValue =
    order.type === 'merge'
      ? order.target_restroom
        ? `${order.target_restroom.code} · ${order.target_restroom.name}`
        : `公厕 ${order.target_restroom_id}`
      : order.new_restroom
        ? `${order.new_restroom.code} · ${order.new_restroom.name}`
        : '审批通过后建档';

  return (
    <Modal
      title={`变更单 ${order.code}`}
      onClose={onClose}
      width={760}
      footer={
        <button type="button" className="btn btn-primary" onClick={onClose}>
          关闭
        </button>
      }
    >
      <div className="inline" style={{ marginBottom: 12 }}>
        <span className="tag tag-primary">{TYPE_LABEL[order.type] || order.type}</span>
        <StatusTag status={order.status} />
      </div>

      <DetailList
        items={[
          {
            label: order.type === 'merge' ? '被撤并公厕' : '被拆分公厕',
            value: order.source_restroom
              ? `${order.source_restroom.code} · ${order.source_restroom.name}`
              : `公厕 ${order.source_restroom_id}`,
          },
          { label: order.type === 'merge' ? '承接公厕' : '拆出新点位', value: targetValue },
          { label: '申请人', value: order.applicant || '-' },
          { label: '提交时间', value: formatDateTime(order.created_at) },
          { label: '审批人', value: order.approver || '-' },
          { label: '审批时间', value: formatDateTime(order.approved_at) },
          { label: '审批意见', value: order.approve_remark || '-' },
          { label: '变更依据', value: order.reason },
        ]}
      />

      {order.type === 'split' && order.issue_assignments?.length ? (
        <>
          <div className="card-title" style={{ marginTop: 16 }}>
            <h3>在办问题划归明细</h3>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>问题ID</th>
                  <th>划归去向</th>
                </tr>
              </thead>
              <tbody>
                {order.issue_assignments.map((item) => (
                  <tr key={item.issue_id}>
                    <td>{item.issue_id}</td>
                    <td>{item.destination === 'new' ? '划归新点位' : '留在原公厕'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <div className="card-title" style={{ marginTop: 16 }}>
        <h3>执行结果</h3>
      </div>
      <SnapshotBlock order={order} />
    </Modal>
  );
}
