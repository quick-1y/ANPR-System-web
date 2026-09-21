// GET /api/system/time — server clock plus the display zone resolved for the caller.
import { api, jfetch } from './api.js';

export function fetchServerTime() {
  return jfetch(api("/api/system/time"));
}
