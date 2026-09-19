import { http } from './client.js';

const RESOURCE = '/assessments';

export const assessmentApi = {
  list: (period) => http.get(RESOURCE, period ? { period } : {}),
  generate: (payload) => http.post(`${RESOURCE}/generate`, payload),
};
