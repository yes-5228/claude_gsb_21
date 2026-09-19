import { http } from './client.js';

const RESOURCE = '/restrooms/adjustments';

export const adjustmentApi = {
  list: (params) => http.get(RESOURCE, params),
  detail: (id) => http.get(`${RESOURCE}/${id}`),
  applyMerge: (payload) => http.post(`${RESOURCE}/merge`, payload),
  applySplit: (payload) => http.post(`${RESOURCE}/split`, payload),
  approve: (id, payload) => http.post(`${RESOURCE}/${id}/approve`, payload),
  reject: (id, payload) => http.post(`${RESOURCE}/${id}/reject`, payload),
  cancel: (id, payload) => http.post(`${RESOURCE}/${id}/cancel`, payload),
  movableIssues: (restroomId) =>
    http.get(`${RESOURCE}/movable-issues`, { restroom_id: restroomId }),
  traceByCode: (code) => http.get(`${RESOURCE}/lineage`, { code }),
  lineage: (restroomId) => http.get(`/restrooms/${restroomId}/lineage`),
};
