// User management — Settings sub-pane (Phase 5)
import { api, jfetch } from './api.js';
import { showToast, switchSettings, openModal, closeModal } from './ui.js';
import { hasPermission } from './state.js';

let _allPermissions = [];
let _users = [];
let _selectedUserId = null;

// --- Init ---

export function initUsersPane() {
    if (!hasPermission("tab:settings")) return;

    const navItem = document.getElementById("snav-users");
    if (navItem) {
        navItem.hidden = false;
        navItem.onclick = () => { switchSettings("users"); loadUsers(); };
    }

    _bindButtons();
}

function _bindButtons() {
    document.getElementById("createUserBtn").onclick = _showCreateForm;
    document.getElementById("cancelCreateUserBtn").onclick = _showEmpty;
    document.getElementById("confirmCreateUserBtn").onclick = _doCreateUser;
    document.getElementById("saveUserBtn").onclick = _doSaveUser;
    document.getElementById("changeUserPasswordBtn").onclick = _openPasswordModal;
    document.getElementById("userPasswordModalClose").onclick = () => closeModal("userPasswordModal");
    document.getElementById("userPasswordCancel").onclick = () => closeModal("userPasswordModal");
    document.getElementById("userPasswordConfirm").onclick = _doChangePassword;
    document.getElementById("userPasswordModal").onclick = (e) => {
        if (e.target.id === "userPasswordModal") closeModal("userPasswordModal");
    };
    document.getElementById("newUserRole").addEventListener("change", () => {
        const role = document.getElementById("newUserRole").value;
        _renderPermCheckboxes("newUserPermissions", [], role);
    });
    document.getElementById("editUserRole").addEventListener("change", () => {
        const role = document.getElementById("editUserRole").value;
        const kept = _getCheckedPermissions("editUserPermissions");
        _renderPermCheckboxes("editUserPermissions", kept, role);
    });
    document.getElementById("newUserPassword").addEventListener("keydown", (e) => {
        if (e.key === "Enter") document.getElementById("confirmCreateUserBtn").click();
    });
    document.getElementById("userConfirmPassword").addEventListener("keydown", (e) => {
        if (e.key === "Enter") document.getElementById("userPasswordConfirm").click();
    });
}

// --- Load ---

export async function loadUsers() {
    try {
        [_users, _allPermissions] = await Promise.all([
            jfetch(api("/api/users")),
            jfetch(api("/api/permissions/available")),
        ]);
    } catch (_e) {
        _users = [];
        _allPermissions = [];
    }
    _renderUserList();

    if (_selectedUserId !== null) {
        const still = _users.find((u) => u.id === _selectedUserId);
        if (still) {
            _showEditForm(still);
        } else {
            _showEmpty();
        }
    }
}

// --- Helpers ---

const _ROLE_BADGES = {
    superadmin: '<span style="font-size:9px;color:var(--accent2);margin-left:4px;font-family:var(--mono)">СА</span>',
    admin:      '<span style="font-size:9px;color:var(--accent2);margin-left:4px;font-family:var(--mono)">АДМ</span>',
    operator:   '<span style="font-size:9px;color:var(--text3);margin-left:4px;font-family:var(--mono)">ОПЕ</span>',
};

function _roleBadge(role) {
    return _ROLE_BADGES[role] ?? `<span style="font-size:9px;color:var(--text3);margin-left:4px;font-family:var(--mono)">${_esc(role)}</span>`;
}

// --- User list ---

function _renderUserList() {
    const el = document.getElementById("userItems");
    if (!el) return;
    el.innerHTML = "";
    for (const u of _users.filter(u => u.role !== "superadmin")) {
        const item = document.createElement("div");
        item.className = "ch-item" + (_selectedUserId === u.id ? " active" : "");
        item.dataset.userId = u.id;

        const roleBadge = _roleBadge(u.role);
        const inactiveTag = u.is_active
            ? ""
            : '<span style="font-size:9px;color:var(--danger);margin-left:4px;font-family:var(--mono)">НЕАКТ</span>';

        item.innerHTML = `<span class="ch-item-name">${_esc(u.login)}</span>${roleBadge}${inactiveTag}`;
        item.onclick = () => _selectUser(u.id);
        el.appendChild(item);
    }
}

function _selectUser(userId) {
    _selectedUserId = userId;
    _renderUserList();
    const user = _users.find((u) => u.id === userId);
    if (!user) return;
    _showEditForm(user);
}

// --- Create form ---

function _showCreateForm() {
    _selectedUserId = null;
    _renderUserList();
    document.getElementById("newUserLogin").value = "";
    document.getElementById("newUserPassword").value = "";
    document.getElementById("newUserPasswordConfirm").value = "";
    document.getElementById("newUserRole").value = "operator";
    document.getElementById("createUserError").textContent = "";
    _renderPermCheckboxes("newUserPermissions", [], "operator");
    document.getElementById("userCreatePane").hidden = false;
    document.getElementById("userEditPane").hidden = true;
    document.getElementById("userConfigEmpty").hidden = true;
    setTimeout(() => document.getElementById("newUserLogin").focus(), 50);
}

async function _doCreateUser() {
    const login = document.getElementById("newUserLogin").value.trim();
    const password = document.getElementById("newUserPassword").value;
    const confirm = document.getElementById("newUserPasswordConfirm").value;
    const role = document.getElementById("newUserRole").value;
    const permissions = _getCheckedPermissions("newUserPermissions");
    const errEl = document.getElementById("createUserError");

    if (!login) { errEl.textContent = "Введите логин"; return; }
    if (!password) { errEl.textContent = "Введите пароль"; return; }
    if (password.length < 4) { errEl.textContent = "Пароль должен содержать не менее 4 символов"; return; }
    if (password !== confirm) { errEl.textContent = "Пароли не совпадают"; return; }
    errEl.textContent = "";

    try {
        const created = await jfetch(api("/api/users"), "POST", { login, password, role, permissions });
        showToast(`Пользователь «${login}» создан`);
        await loadUsers();
        _selectUser(created.id);
    } catch (e) {
        errEl.textContent = _parseError(e);
    }
}

// --- Edit form ---

function _showEditForm(user) {
    document.getElementById("editUserLogin").value = user.login;
    document.getElementById("editUserRole").value = user.role;
    document.getElementById("editUserActive").checked = user.is_active;
    document.getElementById("editUserError").textContent = "";
    _renderPermCheckboxes("editUserPermissions", user.permissions || [], user.role);
    document.getElementById("userCreatePane").hidden = true;
    document.getElementById("userEditPane").hidden = false;
    document.getElementById("userConfigEmpty").hidden = true;
}

async function _doSaveUser() {
    if (_selectedUserId === null) return;
    const role = document.getElementById("editUserRole").value;
    const is_active = document.getElementById("editUserActive").checked;
    const permissions = _getCheckedPermissions("editUserPermissions");
    const errEl = document.getElementById("editUserError");
    errEl.textContent = "";

    try {
        await jfetch(api(`/api/users/${_selectedUserId}`), "PUT", { role, permissions, is_active });
        showToast("Настройки пользователя сохранены");
        await loadUsers();
    } catch (e) {
        errEl.textContent = _parseError(e);
    }
}

// --- Password change ---

function _openPasswordModal() {
    document.getElementById("userNewPassword").value = "";
    document.getElementById("userConfirmPassword").value = "";
    document.getElementById("userPasswordError").textContent = "";
    openModal("userPasswordModal");
    setTimeout(() => document.getElementById("userNewPassword").focus(), 50);
}

async function _doChangePassword() {
    if (_selectedUserId === null) return;
    const newPassword = document.getElementById("userNewPassword").value;
    const confirm = document.getElementById("userConfirmPassword").value;
    const errEl = document.getElementById("userPasswordError");

    if (!newPassword) { errEl.textContent = "Введите пароль"; return; }
    if (newPassword.length < 4) { errEl.textContent = "Пароль должен содержать не менее 4 символов"; return; }
    if (newPassword !== confirm) { errEl.textContent = "Пароли не совпадают"; return; }
    errEl.textContent = "";

    try {
        await jfetch(api(`/api/users/${_selectedUserId}/password`), "PUT", { new_password: newPassword });
        closeModal("userPasswordModal");
        showToast("Пароль изменён");
    } catch (e) {
        errEl.textContent = _parseError(e);
    }
}

// --- Helpers ---

function _showEmpty() {
    _selectedUserId = null;
    _renderUserList();
    document.getElementById("userCreatePane").hidden = true;
    document.getElementById("userEditPane").hidden = true;
    document.getElementById("userConfigEmpty").hidden = false;
}

function _renderPermCheckboxes(containerId, currentPerms, role) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = "";
    for (const p of _allPermissions) {
        if (role === "operator" && p.key === "tab:settings") continue;
        const label = document.createElement("label");
        label.style.cssText = "display:inline-flex;align-items:center;gap:5px;margin-right:12px;margin-bottom:4px;font-size:12px;cursor:pointer";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.value = p.key;
        cb.checked = currentPerms.includes(p.key);
        label.appendChild(cb);
        label.append(p.label);
        el.appendChild(label);
    }
}

function _getCheckedPermissions(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return [];
    return Array.from(el.querySelectorAll("input[type='checkbox']:checked")).map((cb) => cb.value);
}

function _parseError(e) {
    try {
        const body = JSON.parse(e.message);
        if (typeof body.detail === "string") return body.detail;
        if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg || JSON.stringify(d)).join("; ");
        return e.message;
    } catch (_) {
        return e.message || "Произошла ошибка";
    }
}

function _esc(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
