let api = null;
let getApiKey = null;
let showAuthOverlay = null;
let showToast = null;
let openModal = null;
let closeModal = null;
let loadGlobalSettings = null;

let backupBusy = false;
let pendingDbFile = null;
let pendingSettingsFile = null;
let initialized = false;

function setBackupBusy(busy) {
  backupBusy = busy;
  ["dbBackupBtn", "dbRestoreBtn", "settingsBackupBtn", "settingsRestoreBtn"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = busy;
  });
}

async function downloadBackup(url, fallbackName) {
  setBackupBusy(true);
  try {
    const headers = {};
    const k = getApiKey();
    if (k) headers["X-Api-Key"] = k;
    const resp = await fetch(api(url), { headers });
    if (resp.status === 401) {
      showAuthOverlay(() => downloadBackup(url, fallbackName));
      return;
    }
    if (!resp.ok) {
      let detail = "Ошибка скачивания";
      try {
        const j = await resp.json();
        detail = j.detail || detail;
      } catch (_) {}
      showToast(detail, 4000);
      return;
    }
    const blob = await resp.blob();
    const cd = resp.headers.get("Content-Disposition") || "";
    const m = cd.match(/filename="?([^"]+)"?/);
    const filename = m ? m[1] : fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      URL.revokeObjectURL(a.href);
      a.remove();
    }, 200);
    showToast("Файл скачан", 2000);
  } catch (err) {
    showToast("Ошибка: " + err.message, 4000);
  } finally {
    setBackupBusy(false);
  }
}

export function initBackupModule(deps) {
  api = deps.api;
  getApiKey = deps.getApiKey;
  showAuthOverlay = deps.showAuthOverlay;
  showToast = deps.showToast;
  openModal = deps.openModal;
  closeModal = deps.closeModal;
  loadGlobalSettings = deps.loadGlobalSettings;

  if (initialized) return;
  initialized = true;

  document.getElementById("dbBackupBtn").onclick = () => downloadBackup("/api/data/backup/database", "anpr_db_backup.zip");
  document.getElementById("settingsBackupBtn").onclick = () => downloadBackup("/api/data/backup/settings", "settings.yaml");

  document.getElementById("dbRestoreBtn").onclick = () => {
    document.getElementById("dbRestoreFileInput").value = "";
    document.getElementById("dbRestoreFileInput").click();
  };
  document.getElementById("dbRestoreFileInput").onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    pendingDbFile = file;
    document.getElementById("dbRestoreFileName").textContent = file.name;
    openModal("dbRestoreModal");
  };
  document.getElementById("dbRestoreModalClose").onclick = () => {
    pendingDbFile = null;
    closeModal("dbRestoreModal");
  };
  document.getElementById("dbRestoreCancel").onclick = () => {
    pendingDbFile = null;
    closeModal("dbRestoreModal");
  };
  document.getElementById("dbRestoreModal").onclick = (e) => {
    if (e.target.id === "dbRestoreModal") {
      pendingDbFile = null;
      closeModal("dbRestoreModal");
    }
  };
  document.getElementById("dbRestoreConfirm").onclick = async () => {
    closeModal("dbRestoreModal");
    if (!pendingDbFile) return;
    setBackupBusy(true);
    const confirmBtn = document.getElementById("dbRestoreConfirm");
    confirmBtn.disabled = true;
    try {
      const formData = new FormData();
      formData.append("file", pendingDbFile);
      const headers = {};
      const k = getApiKey();
      if (k) headers["X-Api-Key"] = k;
      const resp = await fetch(api("/api/data/backup/database/restore"), {
        method: "POST",
        headers,
        body: formData,
      });
      if (resp.status === 401) {
        showAuthOverlay();
        return;
      }
      const result = await resp.json();
      if (resp.ok && result.status === "ok") {
        showToast("БД восстановлена. Приложение перезапускается...", 8000);
        setTimeout(() => {
          const check = setInterval(async () => {
            try {
              const r = await fetch(api("/api/health"));
              if (r.ok) {
                clearInterval(check);
                location.reload();
              }
            } catch (_) {}
          }, 2000);
          setTimeout(() => clearInterval(check), 120000);
        }, 3000);
      } else {
        showToast(result.detail || "Ошибка восстановления БД", 5000);
      }
    } catch (err) {
      showToast("Ошибка: " + err.message, 5000);
    } finally {
      pendingDbFile = null;
      confirmBtn.disabled = false;
      setBackupBusy(false);
    }
  };

  document.getElementById("settingsRestoreBtn").onclick = () => {
    document.getElementById("settingsRestoreFileInput").value = "";
    document.getElementById("settingsRestoreFileInput").click();
  };
  document.getElementById("settingsRestoreFileInput").onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    pendingSettingsFile = file;
    document.getElementById("settingsRestoreFileName").textContent = file.name;
    openModal("settingsRestoreModal");
  };
  document.getElementById("settingsRestoreModalClose").onclick = () => {
    pendingSettingsFile = null;
    closeModal("settingsRestoreModal");
  };
  document.getElementById("settingsRestoreCancel").onclick = () => {
    pendingSettingsFile = null;
    closeModal("settingsRestoreModal");
  };
  document.getElementById("settingsRestoreModal").onclick = (e) => {
    if (e.target.id === "settingsRestoreModal") {
      pendingSettingsFile = null;
      closeModal("settingsRestoreModal");
    }
  };
  document.getElementById("settingsRestoreConfirm").onclick = async () => {
    closeModal("settingsRestoreModal");
    if (!pendingSettingsFile) return;
    setBackupBusy(true);
    const confirmBtn = document.getElementById("settingsRestoreConfirm");
    confirmBtn.disabled = true;
    try {
      const formData = new FormData();
      formData.append("file", pendingSettingsFile);
      const headers = {};
      const k = getApiKey();
      if (k) headers["X-Api-Key"] = k;
      const resp = await fetch(api("/api/data/backup/settings/restore"), {
        method: "POST",
        headers,
        body: formData,
      });
      if (resp.status === 401) {
        showAuthOverlay();
        return;
      }
      const result = await resp.json();
      if (resp.ok && result.status === "ok") {
        showToast("Настройки восстановлены и применены", 3000);
        await loadGlobalSettings();
      } else {
        showToast(result.detail || "Ошибка восстановления настроек", 5000);
      }
    } catch (err) {
      showToast("Ошибка: " + err.message, 5000);
    } finally {
      pendingSettingsFile = null;
      confirmBtn.disabled = false;
      setBackupBusy(false);
    }
  };
}
