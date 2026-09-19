import { http } from './client.js';

export const assessmentApi = {
  list: (params) => http.get('/assessments', params),
  issue: (restroomId, payload) => http.post(`/assessments/restrooms/${restroomId}`, payload),
};
