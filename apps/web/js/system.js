// System resource and health monitoring
import { api, getToken } from './api.js';
import { loadBarColor } from './ui.js';

export async function refreshSystemResources() {
  if (document.hidden) return;
  try {
    const resources = await (await fetch(api("/api/system/resources"), { headers: (() => { const h = { "Content-Type": "application/json" }; const t = getToken(); if (t) h["Authorization"] = `Bearer ${t}`; return h; })() })).json();
    const cpu = Math.round(Number(resources.cpu_percent) || 0);
    const ram = Math.round(Number(resources.ram_percent) || 0);
    const cpuStat = document.getElementById("cpuStat");
    const ramStat = document.getElementById("ramStat");
    const cpuBar = document.getElementById("cpuBar");
    const ramBar = document.getElementById("ramBar");
    if (cpuStat) cpuStat.textContent = `${cpu}%`;
    if (ramStat) ramStat.textContent = `${ram}%`;
    if (cpuBar) { cpuBar.style.width = `${cpu}%`; cpuBar.style.background = loadBarColor(cpu); }
    if (ramBar) { ramBar.style.width = `${ram}%`; ramBar.style.background = loadBarColor(ram); }
  } catch (_e) {}
}

export async function checkServerHealth() {
  if (document.hidden) return;
  const dot = document.getElementById("serverDot");
  if (!dot) return;
  try {
    const t = getToken();
    const headers = t ? { "Authorization": `Bearer ${t}` } : {};
    const r = await fetch(api("/api/health"), { method: "GET", headers, signal: AbortSignal.timeout(4000) });
    dot.className = r.ok ? "server-dot live" : "server-dot off";
  } catch (_e) { dot.className = "server-dot off"; }
}

export function initSystemPolling() {
  refreshSystemResources();
  setInterval(refreshSystemResources, 10000);
  checkServerHealth();
  setInterval(checkServerHealth, 10000);
}
