import { http } from './client.js';

const RESOURCE = '/change-orders';

export const changeOrderApi = {
  list: (params) => http.get(RESOURCE, params),
  detail: (id) => http.get(`${RESOURCE}/${id}`),
  preview: (params) => http.get(`${RESOURCE}/preview`, params),
  createMerge: (payload) => http.post(`${RESOURCE}/merge`, payload),
  createSplit: (payload) => http.post(`${RESOURCE}/split`, payload),
  approve: (id, payload) => http.post(`${RESOURCE}/${id}/approve`, payload),
  reject: (id, payload) => http.post(`${RESOURCE}/${id}/reject`, payload),
  revoke: (id) => http.post(`${RESOURCE}/${id}/revoke`, payload),
  remove: (id) => http.delete(`${RESOURCE}/${id}`),
};
