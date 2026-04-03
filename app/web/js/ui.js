// UI utilities — tabs, sidebar, toast, modals, datetime, flags, theme

export function flagByCountry(code) {
  const normalized = String(code || "")
    .trim()
    .toLowerCase();
  return normalized
    ? `/web/images/flags/${normalized}.png`
    : "/web/images/flags/eu.png";
}

export function flagHtml(code) {
  const normalized = String(code || "")
    .trim()
    .toLowerCase();
  const src = flagByCountry(normalized || "eu");
  const fallback = flagByCountry("eu");
  return `<img class='ev-flag' src='${src}' alt='${normalized || "unknown"}' onerror="this.onerror=null;this.src='${fallback}'" />`;
}

export function getActiveTabName() {
  return document.querySelector(".ttab.active")?.dataset.tab || "obs";
}

export function getActiveSettingsName() {
  return document.querySelector(".snav-item.active")?.dataset.sp || "general";
}

export function updateTopbarTitle() {
  const titleNode = document.querySelector(".topbar-title");
  if (!titleNode) return;
  const tabLabels = {
    obs: "Наблюдение",
    journal: "Журнал",
    lists: "Списки",
    settings: "Настройки",
  };
  const settingsLabels = {
    general: "Общие",
    channels: "Каналы",
    controllers: "Контроллеры",
    sysdata: "Системные данные",
    debug: "Debug",
  };
  const activeTab = getActiveTabName();
  if (activeTab !== "settings") {
    titleNode.textContent = tabLabels[activeTab] || tabLabels.obs;
    return;
  }
  const activeSettings = getActiveSettingsName();
  titleNode.textContent = `${tabLabels.settings} / ${settingsLabels[activeSettings] || settingsLabels.general}`;
}

export function switchSettings(name) {
  document
    .querySelectorAll(".snav-item")
    .forEach((el) => el.classList.toggle("active", el.dataset.sp === name));
  document
    .querySelectorAll(".settings-pane")
    .forEach((p) => p.classList.remove("active"));
  document.getElementById(`sp-${name}`).classList.add("active");
  updateTopbarTitle();
}

export function switchTab(name) {
  // Do not switch to a tab that has been hidden by permission rules
  const targetTabEl = document.querySelector(`.ttab[data-tab="${name}"]`);
  if (targetTabEl && targetTabEl.style.display === "none") return;
  document
    .querySelectorAll(".ttab")
    .forEach((el) => el.classList.toggle("active", el.dataset.tab === name));
  document
    .querySelectorAll(".tab-pane")
    .forEach((pane) => pane.classList.remove("active"));
  const tabPane = document.getElementById(`tab-${name}`);
  if (!tabPane) return;
  tabPane.classList.add("active");
  updateTopbarTitle();
}

/**
 * Hide sidebar tabs the current user is not permitted to see.
 *
 * @param {string[]} permissions - User's permission keys (e.g. ["tab:obs", "tab:journal"]).
 * @param {boolean} userIsAdmin  - Admins bypass all permission checks (see all tabs).
 *
 * Called from app.js after login / page load with the resolved user object.
 * If the currently active tab becomes hidden, switches to the first visible tab.
 */
export function applyTabVisibility(permissions, userIsAdmin) {
  const tabs = document.querySelectorAll(".ttab");
  const activeTab = getActiveTabName();
  let firstVisible = null;
  let activeTabVisible = false;

  tabs.forEach((el) => {
    const tabName = el.dataset.tab;
    const permitted =
      userIsAdmin ||
      (Array.isArray(permissions) && permissions.includes(`tab:${tabName}`));
    el.style.display = permitted ? "" : "none";
    if (permitted) {
      if (!firstVisible) firstVisible = tabName;
      if (tabName === activeTab) activeTabVisible = true;
    }
  });

  if (!activeTabVisible && firstVisible) {
    switchTab(firstVisible);
  }
}

export function loadBarColor(pct) {
  if (pct < 50) return "#2ecc71";
  if (pct < 80) return "#f5a623";
  return "#e74c3c";
}

export function normalizeDirectionCode(direction) {
  const value = String(direction || "").trim().toUpperCase();
  return (!value || value === "UNKNOWN") ? "" : value;
}

export function formatDirection(directionValue) {
  const normalized = String(directionValue || "").toUpperCase();
  const isApproaching =
    normalized === "IN" ||
    normalized === "APPROACHING" ||
    normalized === "APPROACH";
  const isReceding =
    normalized === "OUT" ||
    normalized === "RECEDING" ||
    normalized === "RECEDE";

  if (isApproaching) {
    return {
      badgeClass: "badge-in",
      label: "→ Приближение",
      plain: "Приближение",
    };
  }

  if (isReceding) {
    return {
      badgeClass: "badge-out",
      label: "← Отдаление",
      plain: "Отдаление",
    };
  }

  return {
    badgeClass: "badge-out",
    label: "—",
    plain: "—",
  };
}

export function normalizePlate(plate) {
  return (plate || "").toUpperCase().replace(/\s/g, "");
}

export function showToast(message, duration = 2000) {
  const existing = document.getElementById("appToast");
  if (existing) existing.remove();
  const toast = document.createElement("div");
  toast.id = "appToast";
  toast.className = "app-toast";
  toast.textContent = message;
  document.body.appendChild(toast);
  requestAnimationFrame(() => {
    requestAnimationFrame(() => toast.classList.add("app-toast-visible"));
  });
  setTimeout(() => {
    toast.classList.remove("app-toast-visible");
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

export function openModal(id) { document.getElementById(id).classList.add("active"); }
export function closeModal(id) { document.getElementById(id).classList.remove("active"); }

export function applyTheme(theme) {
  const normalized = String(theme || "dark").toLowerCase() === "light" ? "light" : "dark";
  document.body.setAttribute("data-theme", normalized);
  try {
    localStorage.setItem("anpr_theme", normalized);
  } catch (_e) {}
}

export function updateTopbarDateTime() {
  const dateEl = document.getElementById("topbarDate");
  const timeEl = document.getElementById("topbarTime");
  if (!dateEl && !timeEl) return;
  const now = new Date();
  if (dateEl) dateEl.textContent = now.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
  if (timeEl) timeEl.textContent = now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// DOM form helpers
export function val(id) {
  return document.getElementById(id).value;
}
export function setVal(id, v) {
  document.getElementById(id).value = v ?? "";
}
export function setChk(id, v) {
  document.getElementById(id).checked = !!v;
}
export function parseIds(raw) {
  return String(raw || "")
    .split(",")
    .map((x) => Number(x.trim()))
    .filter((x) => Number.isFinite(x));
}

// Sidebar
let sidebarLocked = false;
export function applySidebarLocked(locked) {
  sidebarLocked = !!locked;
  const rail = document.getElementById("leftRail");
  if (sidebarLocked) {
    rail.classList.remove("rail-expanded");
  }
}

export function initSidebarHover() {
  const rail = document.getElementById("leftRail");
  rail.addEventListener("mouseenter", () => {
    if (sidebarLocked) return;
    rail.classList.add("rail-expanded");
  });
  rail.addEventListener("mouseleave", () => {
    rail.classList.remove("rail-expanded");
  });
}
