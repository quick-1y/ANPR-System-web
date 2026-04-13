# Roadmap: Clients & Lists Separation Refactor

---

## 1. Current-State Analysis

**How the functionality is organized today:**

- `database/lists_repository.py` — single `ListDatabase` class manages both `lists` table (list metadata) and `clients` table (plate records). Both are tightly coupled in one module.
- `app/api/routers/lists.py` — single router handles all CRUD for both lists and clients (called "entries" in the API).
- `app/web/js/lists.js` — single frontend module handles both list management UI and client/entry management UI.
- `app/web/index.html` — has a single "Lists" top-level tab.

**Coupling between lists and clients:**

- `clients.list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE` — a client **must** belong to a list; no standalone clients exist.
- All client CRUD endpoints are nested under `/api/lists/{list_id}/entries/*`.
- Frontend state: `state.selectedListId` drives which entries are visible; there is no client-level state independent of list selection.

**Risky areas for channel filtering:**

- `ControllerAutomationService` in `controllers/service.py` calls `lists_db.plate_in_list_type(plate, type)` and `lists_db.plate_in_lists(plate, list_ids)` directly — these are the core channel filtering functions. Any rename or signature change here breaks relay automation.
- `lists_db.find_entry_by_plate(plate)` is used for event enrichment (attaching client name to events) — must remain working.
- `channels.list_filter_mode` and `channels.list_filter_list_ids` must remain semantically unchanged in the DB.

---

## 2. Target Architecture

**Frontend structure:**

```
Clients (top-level tab)
├── Clients (subtab)
│   ├── Client list table (all clients, independent of lists)
│   ├── Add Client button → reuse existing entry form fields
│   └── Client Card (modal/panel)
│       ├── View/Edit/Delete
│       ├── Current list attachment shown
│       ├── Attach to List button → List Picker modal
│       └── Detach from List button
└── Lists (subtab)
    ├── List sidebar (same as current)
    ├── List type/name edit (same as current)
    ├── Members table (clients attached to this list)
    ├── Attach Client button → Client Picker modal (with search)
    └── Client row → opens Client Card with "Detach from List" button
```

**Backend/module structure:**

```
database/
├── clients_repository.py   # ClientDatabase — clients CRUD + search + attach/detach
└── lists_repository.py     # ListDatabase — lists CRUD + plate matching (for channels, events)

app/api/routers/
├── clients.py              # /api/clients/* endpoints
└── lists.py                # /api/lists/* endpoints (trimmed — no entry CRUD)
```

**Data model changes:**

```sql
-- clients: make list_id nullable (client may exist without a list)
-- Change: list_id BIGINT NOT NULL REFERENCES lists(id) ON DELETE CASCADE
-- To:     list_id BIGINT REFERENCES lists(id) ON DELETE SET NULL

-- No other schema changes required
-- channels table: unchanged
-- lists table: unchanged
```

---

## 3. Step-by-Step Implementation Roadmap

### Phase 1 — Backend: Schema & Repository Split

**Task 1.1 — Update `clients` table schema in `lists_repository.py`**
- Change `list_id BIGINT NOT NULL` → `list_id BIGINT REFERENCES lists(id) ON DELETE SET NULL` (nullable)
- Remove the `ON DELETE CASCADE` from the list-to-clients relation
- This is a CREATE TABLE change (DB recreated fresh each run)

**Task 1.2 — Create `database/clients_repository.py`**
- New `ClientDatabase` class with its own DB pool
- Move and rename these methods from `ListDatabase`:
  - `add_entry()` → `create_client()` (signature: no `list_id` required)
  - `update_entry()` → `update_client()`
  - `delete_entry()` → `delete_client()`
  - `list_entries(list_id)` → keep in `ListDatabase` as `list_clients_in_list(list_id)` (for list membership view)
  - `find_entry_by_plate()` → rename to `find_client_by_plate()` (kept in `ListDatabase` for backward compat, or delegate)
- Add new methods to `ClientDatabase`:
  - `list_all_clients()` — returns all non-deleted clients (no list filter)
  - `get_client(client_id)` — fetch single client record
  - `search_clients(query)` — search by last_name, first_name, middle_name, plate (ILIKE)
  - `attach_to_list(client_id, list_id)` — sets `clients.list_id = list_id`
  - `detach_from_list(client_id)` — sets `clients.list_id = NULL`

**Task 1.3 — Trim `database/lists_repository.py`**
- Remove: `add_entry()`, `update_entry()`, `delete_entry()`
- Keep: `create_list()`, `list_lists()`, `update_list()`, `delete_list()`
- Keep: `list_clients_in_list(list_id)` — used by Lists subtab to show members
- Keep: `all_plates_with_type()` — used for plate lookup
- Keep: `plate_in_list_type()` — used by channel automation (DO NOT RENAME SIGNATURE)
- Keep: `plate_in_lists()` — used by channel automation (DO NOT RENAME SIGNATURE)
- Keep: `find_entry_by_plate()` → rename to `find_client_by_plate()` and update all call sites

**Task 1.4 — Wire `ClientDatabase` into the container**
- In `app/api/container.py`: instantiate `ClientDatabase(dsn)` alongside existing `ListDatabase`
- Pass `clients_db` to routers that need it

---

### Phase 2 — Backend: API Routes

**Task 2.1 — Create `app/api/routers/clients.py`**

| Method | Endpoint | Action |
|--------|----------|--------|
| GET | `/api/clients` | List all clients |
| POST | `/api/clients` | Create client (no list_id in body) |
| GET | `/api/clients/{id}` | Get single client |
| PUT | `/api/clients/{id}` | Update client fields |
| DELETE | `/api/clients/{id}` | Soft-delete client |
| GET | `/api/clients/search?q=` | Search clients |
| POST | `/api/clients/{id}/attach` | Attach to list (`{list_id: int}`) |
| DELETE | `/api/clients/{id}/attach` | Detach from list |

**Task 2.2 — Update `app/api/routers/lists.py`**
- Remove: all `/api/lists/{list_id}/entries/*` endpoints
- Keep: `GET /api/lists`, `POST /api/lists`, `PUT /api/lists/{id}`, `DELETE /api/lists/{id}`
- Keep: `GET /api/lists/plates` (`all_plates_with_type` — do not change URL or behavior)
- Keep: `GET /api/lists/entry-by-plate` (same URL — do not break anything calling it)
- Add: `GET /api/lists/{list_id}/clients` — list clients in a list (replaces `/entries`)

**Task 2.3 — Update Pydantic schemas in `app/api/schemas.py`**
- Add: `ClientPayload` (plate, last_name, first_name, middle_name, phone, car, comment) — no list_id
- Add: `AttachClientPayload` (list_id: int)
- Keep: `ListPayload`, `UpdateListPayload` — unchanged
- Remove: `EntryPayload` (replaced by `ClientPayload`)

**Task 2.4 — Register new router in `app/api/main.py`**
- `app.include_router(clients_router)` alongside existing routers

---

### Phase 3 — Frontend: HTML Structure

**Task 3.1 — Update `app/web/index.html`**
- Rename top-level "Lists" tab to "Clients"
- Inside the Clients section, add two sub-tab buttons: "Clients" and "Lists"
- Create a new panel for the Clients subtab (client table + add button)
- Keep the existing Lists panel as the Lists subtab
- Add new modals:
  - Client Card modal (view/edit/delete + list attachment info + attach/detach buttons)
  - List Picker modal (shown when clicking "Attach to List" from a client card)
  - Client Picker modal (shown when clicking "Attach Client" in a list, includes search field)
- Reuse the existing entry form fields (plate, last_name, first_name, etc.) in the client creation modal

---

### Phase 4 — Frontend: JavaScript Modules

**Task 4.1 — Create `app/web/js/clients.js`**
- State: `state.allClients`, `state.selectedClientId`
- `loadAllClients()` — fetches `GET /api/clients`
- `renderClientsTable()` — renders client rows, each row clickable
- `openClientCard(clientId)` — opens client card modal, fetches full client data
- `openAddClientModal()` — reuse existing entry form, POST to `/api/clients`
- `saveClientChanges(clientId)` — PUT to `/api/clients/{id}`
- `deleteClient(clientId)` — DELETE with confirmation
- `openListPickerModal(clientId)` — loads available lists, shows "Attach" button per list
- `attachClientToList(clientId, listId)` — POST to `/api/clients/{id}/attach`
- `detachClientFromList(clientId)` — DELETE to `/api/clients/{id}/attach`
- `searchClients(query)` — debounced, calls `GET /api/clients/search?q=...`, re-renders table

**Task 4.2 — Refactor `app/web/js/lists.js`**
- Remove: `loadEntries()`, `openEditEntryModal()`, `openDeleteEntryModal()`, entry form bindings
- Remove: add/edit/delete entry event handlers
- Keep: `loadLists()`, `renderLists()`, `refreshPlateLookup()`, `renderCustomListOptions()`
- Keep: CSV import/export (reuse for list members if needed, or defer)
- Add: `loadListClients(listId)` — fetches `GET /api/lists/{id}/clients`
- Add: `renderListClientsTable(clients)` — renders members table; each row opens Client Card
- Add: `openClientPickerModal(listId)` — shows all clients with search field; each has "Attach" button; calls `POST /api/clients/{id}/attach`

**Task 4.3 — Update `app/web/js/app.js`**
- Import and initialize `clients.js` module
- Wire sub-tab switching logic (Clients ↔ Lists within the Clients top-level tab)
- Ensure `loadAllClients()` and `loadLists()` are both called on app init

**Task 4.4 — Add confirmation dialogs for all destructive/attaching operations**
- All operations (create, edit, delete client; attach, detach; delete list) must trigger a confirmation modal before proceeding
- Reuse existing `ui.js` modal/confirm utilities

---

### Phase 5 — Cleanup & Verification

**Task 5.1 — Verify container wiring in `app/api/container.py`**
- Confirm `lists_db.plate_in_list_type` and `lists_db.plate_in_lists` still injected into `ControllerAutomationService` (no changes needed — just confirm)

**Task 5.2 — Rename `find_entry_by_plate` → `find_client_by_plate`**
- Update the method in `lists_repository.py`
- Grep all call sites (routers, workers, services) and update atomically

**Task 5.3 — Update `tests/test_lists_repository.py`**
- Add tests for `ClientDatabase` methods
- Update existing tests that referenced `add_entry`/`delete_entry` to use new names

---

## 4. API & Data-Flow Considerations

**Endpoints changing:**

| Old | New | Notes |
|-----|-----|-------|
| `POST /api/lists/{id}/entries` | `POST /api/clients` | No list_id in body |
| `PUT /api/lists/{id}/entries/{eid}` | `PUT /api/clients/{id}` | Flat, not nested |
| `DELETE /api/lists/{id}/entries/{eid}` | `DELETE /api/clients/{id}` | |
| `GET /api/lists/{id}/entries` | `GET /api/lists/{id}/clients` | Same purpose, clearer name |
| *(new)* | `GET /api/clients` | All clients |
| *(new)* | `GET /api/clients/search?q=` | Search |
| *(new)* | `POST /api/clients/{id}/attach` | Attach to list |
| *(new)* | `DELETE /api/clients/{id}/attach` | Detach from list |

**Attachment/detachment flow:**
- Attaching: `POST /api/clients/{id}/attach` with `{list_id: N}` → `UPDATE clients SET list_id = N WHERE id = ?`
- Detaching: `DELETE /api/clients/{id}/attach` → `UPDATE clients SET list_id = NULL WHERE id = ?`
- A client can only be in one list at a time (singular `list_id` FK)
- Attaching to a new list while already attached implicitly replaces the previous attachment (UPDATE overwrites)

**Confirmation flow:**
- Frontend sends the operation request only after user confirms in a modal
- No backend-side confirmation required — treat as standard mutations
- Reuse existing `ui.js` confirm pattern

---

## 5. Naming Cleanup

| Current name | Proposed name | Reason |
|---|---|---|
| `list_entries()` | `list_clients_in_list(list_id)` | "entries" is ambiguous |
| `add_entry()` | `create_client()` | Consistent with domain language |
| `update_entry()` | `update_client()` | Same |
| `delete_entry()` | `delete_client()` | Same |
| `find_entry_by_plate()` | `find_client_by_plate()` | Domain clarity |
| `EntryPayload` (schema) | `ClientPayload` | Match domain |
| `state.currentEntries` | `state.listMembers` | Disambiguate from all clients |
| `openEditEntryModal()` | `openClientCard()` | Reflects new UI concept |
| `/api/lists/{id}/entries` | `/api/lists/{id}/clients` | Match domain |
| `entries_count` (in list response) | `clients_count` | Match domain |

**Names to preserve without change (critical for channel filtering):**
- `plate_in_list_type()` — called by `ControllerAutomationService`
- `plate_in_lists()` — called by `ControllerAutomationService`
- `all_plates_with_type()` — called by frontend for plate lookup
- `list_filter_mode`, `list_filter_list_ids` — DB column names in `channels`

---

## 6. Risks & Compatibility Checks

**Risk 1 — `list_id` becomes nullable on clients**
- Impact: `plate_in_lists()` and `plate_in_list_type()` query `clients JOIN lists` — NULL `list_id` rows won't join, so they are naturally excluded from channel filtering
- Action: verify the JOIN condition in both methods after schema change; no logic change expected

**Risk 2 — `ON DELETE CASCADE` removal**
- Previously, deleting a list deleted all its clients. Now clients survive with `list_id = NULL`.
- Action: update `delete_list()` in `lists_repository.py` — issue `UPDATE clients SET list_id = NULL WHERE list_id = ?` before or instead of relying on CASCADE

**Risk 3 — `ControllerAutomationService` injection**
- Currently wired as: `plate_in_list_type=lists_db.plate_in_list_type, plate_in_lists=lists_db.plate_in_lists`
- These must remain in `ListDatabase` (not moved to `ClientDatabase`)
- Action: confirm these methods stay in `lists_repository.py`, no signature change

**Risk 4 — `renderCustomListOptions()` in `lists.js`**
- Called from `channels.js` to render list checkboxes in channel config
- Must remain in `lists.js` and continue to export correctly
- Action: do not move or rename this function during the split

**Risk 5 — Event enrichment via `find_entry_by_plate()`**
- Used for attaching client name/info to logged events
- Action: grep all call sites before renaming; update all of them atomically in Task 5.2

**Risk 6 — Plate lookup (`state.plateLookup`) excludes unattached clients**
- `refreshPlateLookup()` calls `GET /api/lists/plates` → `all_plates_with_type()`
- A client with `list_id = NULL` should NOT appear in `all_plates_with_type()` — the JOIN with `lists` naturally excludes them
- Action: verify this after schema change — this is the single most important check for channel behavior correctness

---

## 7. Final Recommended Execution Order

```
[x] 1.1  Schema: make clients.list_id nullable, remove NOT NULL and CASCADE
[x] 1.2  Create clients_repository.py with ClientDatabase class
[x] 1.3  Trim lists_repository.py (remove entry CRUD methods, keep channel-critical ones)
[x] 1.4  Wire ClientDatabase into container.py
[x] 2.3  Add ClientPayload and AttachClientPayload schemas
[x] 2.1  Create routers/clients.py with all /api/clients/* endpoints
[x] 2.2  Update routers/lists.py (remove entry endpoints, add /api/lists/{id}/clients)
[x] 2.4  Register clients_router in main.py
[x] 5.2  Rename find_entry_by_plate → find_client_by_plate at all call sites
[x] 3.1  HTML: rename tab, add sub-tabs, add new modals
[x] 4.1  Create clients.js module
[x] 4.2  Refactor lists.js (remove entry logic, add list member + client picker logic)
[x] 4.3  Update app.js (import clients.js, wire sub-tab switching)
[x] 4.4  Add confirmation dialogs to all operations
[x] 5.1  Verify container wiring (lists_db channel functions still injected correctly)
[x] 5.3  Update test_lists_repository.py
[ ] --   Manual check: channel filter still works (plate_in_lists, plate_in_list_type)
[ ] --   Manual check: all_plates_with_type excludes unattached clients
[ ] --   Manual check: event enrichment (find_client_by_plate) still works
```
