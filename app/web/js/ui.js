let onObsTabActivated = null;

export function initUI(deps = {}) {
  onObsTabActivated = deps.onObsTabActivated || null;
}

export function openModal(id) {
  document.getElementById(id).classList.add("active");
}

export function closeModal(id) {
  document.getElementById(id).classList.remove("active");
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

export function switchTab(name) {
  document
    .querySelectorAll(".ttab")
    .forEach((el) => el.classList.toggle("active", el.dataset.tab === name));
  document
    .querySelectorAll(".tab-pane")
    .forEach((p) => p.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  updateTopbarTitle();
  if (name === "obs" && onObsTabActivated) {
    onObsTabActivated();
  }
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

function getActiveTabName() {
  return document.querySelector(".ttab.active")?.dataset.tab || "obs";
}

function getActiveSettingsName() {
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
