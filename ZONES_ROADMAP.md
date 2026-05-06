# ZONES_ROADMAP.md
# Parking Zones Feature — Design & Implementation Roadmap

**System:** ANPR System v0.8 (web)  
**Feature:** Optional Zones mode for parking area entry/exit tracking  
**Database assumption:** Fresh empty database — no migration scripts required  
**Date:** 2026-04-15

> Актуализация 2026-05-06: события зон теперь хранят отдельные поля въезда и выезда: `channel_id_entry` / `channel_id_exit`, `frame_path_entry` / `frame_path_exit`, `plate_path_entry` / `plate_path_exit`. Выездной канал обновляет найденную открытую запись и поднимает её вверх по `time`; если открытого въезда нет или номер не прошёл eligibility, создаётся отдельное событие выездной попытки без вызова реле.

---

## Table of Contents

1. [Current-State Impact Analysis](#1-current-state-impact-analysis)
2. [Data Model Design](#2-data-model-design)
3. [Backend Architecture Changes](#3-backend-architecture-changes)
4. [Event Processing Flow Changes](#4-event-processing-flow-changes)
5. [Controller / Relay Decision Flow](#5-controller--relay-decision-flow)
6. [API Changes](#6-api-changes)
7. [Frontend Changes](#7-frontend-changes)
8. [Zone Deletion and Reset Behavior](#8-zone-deletion-and-reset-behavior)
9. [Non-Zone Compatibility Behavior](#9-non-zone-compatibility-behavior)
10. [Edge Cases and Risks](#10-edge-cases-and-risks)
11. [Phased Implementation Plan](#11-phased-implementation-plan)
12. [Testing Plan](#12-testing-plan)
13. [Documentation Update Plan](#13-documentation-update-plan)

---

## 1. Current-State Impact Analysis

### What changes and why

| Area | File(s) | Nature of Change |
|---|---|---|
| DB schema | `database/postgres/schema.sql` | Redesign events table; add zones table; add zone columns to channels |
| Events repository | `database/postgres_event_repository.py` | All queries, `_to_dict`, new `update_event_exit` method |
| Channel repository | `database/channel_repository.py` | Add zone columns to schema, SELECT, INSERT, UPDATE, `_row_to_dict`, `_normalize` |
| Channel runtime | `runtime/channel_runtime.py` | Zone dispatch logic in `_run_channel`; exit channels skip insert, call update instead |
| Controller automation | `controllers/service.py` | Relay decision logic unchanged in structure; feed correct event dict for exit channel |
| App container | `app/api/container.py` | Wire `ZoneDatabase`; pass it to channel processor for zone eligibility lookup |
| API routers | `app/api/routers/` | New `zones.py` router; update `channels.py` and `events.py` |
| API schemas | `app/api/schemas.py` | New zone payloads; extend `ChannelConfigPayload` |
| Frontend | `app/web/js/`, `app/web/index.html` | New `zones.js` module; update `channels.js`, `events.js`, `journal.js`, `app.js` |

### What does NOT change

- `ANPRPipeline`, `TrackAggregator`, `YOLODetector`, `CRNNRecognizer` — untouched  
- `ControllerAutomationService._resolve_channel_controller_action` — relay decision logic is unchanged  
- Auth, users, lists, clients, controllers, settings, debug — no changes  
- `EventBus`, `DebugRegistry` — no changes  
- `ChannelProcessor.start/stop/restart`, `_filter_detections_by_roi` — no changes  
- Direction estimation and filtering — unchanged  

### Key coupling points to manage carefully

**`runtime/channel_runtime.py` → `_run_channel()`** is the single function responsible for event creation. All zone logic for entry/exit branching must live here or be delegated from here. The function currently calls `self._events_db.insert_event()` unconditionally. This becomes conditional for exit channels.

**`ControllerAutomationService.dispatch_event()`** reads `event["plate"]` and `event["channel_id"]` from the event dict, then looks up the channel config. For exit channels, no new event is created; we must still call `self._event_callback(event)` with a synthetic event dict so the relay fires correctly. That dict must carry `channel_id`, `plate`, and `direction`.

**`database/postgres_event_repository.py`** contains hardcoded column name `timestamp` in every query and in `_to_dict`. Renaming it to `time` requires updating every query, every index reference, the cursor-based pagination `(timestamp, id) < (%s, %s)`, and the `fetch_for_export` filter. This is the highest-churn change in the project.

---

## 2. Data Model Design

### 2.1 Zones table (new)

```sql
CREATE TABLE IF NOT EXISTS zones (
    id   SERIAL PRIMARY KEY,
    name TEXT    NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 0
);
```

No soft-delete. Zones are explicitly deleted by operator action. Cascade to channels via FK.

**Design note on free spaces:**  
`free_spaces = capacity - COUNT(*) FROM events WHERE zone_id = zone.id AND time_exit IS NULL`  
This query runs at read time (zone detail endpoint). It is efficient only with the index on `(zone_id, time_exit)`. Do not cache this value in the zones table — it would require updating it on every event insert and exit update, creating a write-heavy synchronization problem.

### 2.2 Events table (redesigned)

Replace the current events table entirely. Column-by-column rationale follows.

```sql
CREATE TABLE IF NOT EXISTS events (
    id           BIGSERIAL    PRIMARY KEY,
    time         TIMESTAMPTZ  NOT NULL,
    channel_id   INTEGER,
    plate        TEXT         NOT NULL,
    plate_display TEXT,
    country      TEXT,
    confidence   DOUBLE PRECISION,
    source       TEXT,
    frame_path   TEXT,
    plate_path   TEXT,
    direction    TEXT,
    client_id    BIGINT,
    zone_id      INTEGER,
    time_entry   TIMESTAMPTZ,
    time_exit    TIMESTAMPTZ
);
```

**Removed columns:**  
- `channel` (TEXT) — redundant with `channel_id`; channel name at query time comes from a join or frontend lookup. All existing code that filters/sorts by `channel` text must move to `channel_id`.

**Renamed columns:**  
- `timestamp → time` — `timestamp` is a reserved word in SQL; `time` is more semantically accurate and avoids quoting. All queries, indexes, pagination cursors, and API responses must use `time`.

**New columns:**  
- `zone_id INTEGER` — NULL means no zone was involved. `0` is a sentinel meaning "vehicle has exited and is now outside the zone." Values `> 0` reference a zone.id. No FK constraint on zone_id: events are historical records and must survive zone deletion.
- `time_entry TIMESTAMPTZ` — Written when a vehicle enters through a zone-enabled entry channel (subject to list mode eligibility).
- `time_exit TIMESTAMPTZ` — Written when a vehicle exits through a zone-enabled exit channel (subject to list mode eligibility).

**Indexes:**

```sql
CREATE INDEX IF NOT EXISTS idx_events_plate
    ON events(plate);

CREATE INDEX IF NOT EXISTS idx_events_time_id_desc
    ON events(time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_events_channel_id_time_id_desc
    ON events(channel_id, time DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_events_client_id
    ON events(client_id) WHERE client_id IS NOT NULL;

-- For zone occupancy count (free spaces calculation)
CREATE INDEX IF NOT EXISTS idx_events_zone_active
    ON events(zone_id) WHERE zone_id IS NOT NULL AND zone_id > 0 AND time_exit IS NULL;

-- For exit-channel plate lookup: find most recent active entry for a plate in a zone
CREATE INDEX IF NOT EXISTS idx_events_plate_zone_open
    ON events(plate, zone_id, time DESC)
    WHERE zone_id > 0 AND time_exit IS NULL;
```

### 2.3 Channels table (extended)

Add two columns to the existing `channels` DDL in `channel_repository.py`:

```sql
zone_id           INTEGER REFERENCES zones(id) ON DELETE SET NULL,
zone_channel_type TEXT    -- 'entry', 'exit', or NULL (no zone participation)
```

`ON DELETE SET NULL` on `zone_id` ensures that when a zone is deleted, affected channels automatically lose their zone assignment. `zone_channel_type` must then also be cleared to NULL in the same transaction — handled in the ZoneDatabase delete method.

**Valid `zone_channel_type` values:** `'entry'`, `'exit'`, `NULL`  
Enforced via application-level validation in `_normalize()` and the Pydantic schema. No DB CHECK constraint needed for now.

### 2.4 Complete schema.sql

The file `database/postgres/schema.sql` bootstraps all tables at startup via `PooledDatabase._ensure_schema()`. The complete new content:

```sql
-- ── Zones ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS zones (
    id       SERIAL  PRIMARY KEY,
    name     TEXT    NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 0
);

-- ── Events ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id            BIGSERIAL    PRIMARY KEY,
    time          TIMESTAMPTZ  NOT NULL,
    channel_id    INTEGER,
    plate         TEXT         NOT NULL,
    plate_display TEXT,
    country       TEXT,
    confidence    DOUBLE PRECISION,
    source        TEXT,
    frame_path    TEXT,
    plate_path    TEXT,
    direction     TEXT,
    client_id     BIGINT,
    zone_id       INTEGER,
    time_entry    TIMESTAMPTZ,
    time_exit     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_events_plate
    ON events(plate);
CREATE INDEX IF NOT EXISTS idx_events_time_id_desc
    ON events(time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel_id_time_id_desc
    ON events(channel_id, time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_client_id
    ON events(client_id) WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_zone_active
    ON events(zone_id) WHERE zone_id IS NOT NULL AND zone_id > 0 AND time_exit IS NULL;
CREATE INDEX IF NOT EXISTS idx_events_plate_zone_open
    ON events(plate, zone_id, time DESC)
    WHERE zone_id > 0 AND time_exit IS NULL;

-- ── Users (auth) ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    login               TEXT      NOT NULL UNIQUE,
    password            TEXT      NOT NULL,
    role                TEXT      NOT NULL DEFAULT 'operator',
    permissions         JSONB     NOT NULL DEFAULT '[]'::jsonb,
    is_active           BOOLEAN   NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    password_changed_at TIMESTAMPTZ DEFAULT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users(login);
```

*(Channel, list, client, controller tables are owned by their repositories' `_schema_sql()` methods and remain unchanged in structure except for the two new zone columns added in `channel_repository.py`.)*

---

## 3. Backend Architecture Changes

### 3.1 New file: `database/zones_repository.py`

**Responsibilities:**  
- CRUD for the `zones` table  
- Zone-aware channel cascade (set `zone_id = NULL`, `zone_channel_type = NULL`) on zone deletion  
- Occupancy query: count of active (un-exited) entries per zone  

**Key methods:**

```python
class ZoneDatabase(PooledDatabase):
    def list_zones(self) -> list[dict]
    def get_zone(self, zone_id: int) -> dict | None
    def create_zone(self, name: str, capacity: int) -> int
    def update_zone(self, zone_id: int, name: str, capacity: int) -> bool
    def delete_zone(self, zone_id: int) -> bool
        # In one transaction:
        #   UPDATE channels SET zone_id=NULL, zone_channel_type=NULL WHERE zone_id=%s
        #   DELETE FROM zones WHERE id=%s
    def get_channels_for_zone(self, zone_id: int) -> list[dict]
        # SELECT id, name FROM channels WHERE zone_id = %s
    def get_zone_occupancy(self, zone_id: int) -> int
        # SELECT COUNT(*) FROM events WHERE zone_id = %s AND time_exit IS NULL
```

`ZoneDatabase` uses the same DSN and shared pool as the other repositories.

### 3.2 Updates to `database/postgres_event_repository.py`

**`_to_dict` update** — map new column positions. Remove `channel` (text). Add `zone_id`, `time_entry`, `time_exit`.

**`insert_event` signature change** — add optional `zone_id`, `time_entry`:

```python
def insert_event(
    self,
    plate: str,
    channel_id: int | None = None,
    ...,
    zone_id: int | None = None,
    time_entry: str | None = None,
) -> int
```

**New method `find_active_entry_and_write_exit`:**

```python
def find_active_entry_and_write_exit(
    self,
    plate: str,
    zone_id: int,
    time_exit_iso: str,
) -> int | None:
    """
    Find the most recent open entry event for `plate` in `zone_id`
    (where time_exit IS NULL), write time_exit and set zone_id = 0.
    Returns the updated event id, or None if no open entry found.
    """
```

SQL:
```sql
UPDATE events
SET time_exit = %s, zone_id = 0
WHERE id = (
    SELECT id FROM events
    WHERE plate = %s
      AND zone_id = %s
      AND time_exit IS NULL
    ORDER BY time DESC
    LIMIT 1
)
RETURNING id
```

**All existing SELECT queries** — replace `timestamp` with `time` throughout. Update pagination cursor `(timestamp, id) < (%s, %s)` → `(time, id) < (%s, %s)`. Remove `channel` column from all SELECT column lists. Add `zone_id, time_entry, time_exit` to all SELECT column lists.

**`fetch_for_export`** — remove `channel` text filter parameter. Keep `channel_id` filter. Update column references.

### 3.3 Updates to `database/channel_repository.py`

**`_SCHEMA`** — add to CREATE TABLE:

```sql
zone_id           INTEGER,
zone_channel_type TEXT
```

**`_SELECT_COLS`** — append `, zone_id, zone_channel_type`

**`_row_to_dict`** — map two new fields from row positions 28, 29:

```python
"zone_id": row[28],
"zone_channel_type": row[29],
```

**`_normalize`** — add normalization block:

```python
zone_id = result.get("zone_id")
if zone_id in (None, 0, "", "0"):
    zone_id = None
else:
    try:
        zone_id = int(zone_id)
        if zone_id <= 0:
            zone_id = None
    except (TypeError, ValueError):
        zone_id = None
result["zone_id"] = zone_id

zone_type = str(result.get("zone_channel_type") or "").strip().lower()
if zone_type not in ("entry", "exit"):
    zone_type = None
# If no zone assigned, clear the type too
if zone_id is None:
    zone_type = None
result["zone_channel_type"] = zone_type
```

**`create_channel` and `update_channel`** — include `zone_id`, `zone_channel_type` in INSERT and UPDATE.

### 3.4 Updates to `app/api/container.py`

Import and wire `ZoneDatabase`:

```python
from database.zones_repository import ZoneDatabase

@dataclass
class AppContainer:
    ...
    zone_db: ZoneDatabase
```

In `AppContainer.build()`:
```python
zone_db = ZoneDatabase(dsn)
```

In `AppContainer.refresh_storage_clients()`:
```python
self.zone_db = ZoneDatabase(dsn)
```

Pass `zone_db` to the channel processor:
```python
return ChannelProcessor(
    ...
    events_db=self.events_db,
    lists_db=self.lists_db,
    zones_db=self.zone_db,
)
```

### 3.5 Updates to `runtime/channel_runtime.py`

See Section 4 (Event Processing Flow) for the detailed processing logic.

**Constructor change** — add `zones_db` parameter (optional for backwards compatibility of tests):

```python
def __init__(self, ..., zones_db=None) -> None:
    ...
    self._zones_db = zones_db
```

---

## 4. Event Processing Flow Changes

### 4.1 Current flow (simplified)

```
plate detected
  → find client_id
  → build event dict
  → insert_event() → returns event_id
  → _event_callback(event)  →  ControllerAutomationService.dispatch_event()
                             →  EventBus.publish()
```

### 4.2 Zone-aware flow

The zone check happens in `_run_channel()` after plate recognition, before writing to the database. The channel config dict is loaded once at thread start (`channel = dict(ctx.channel)`), so `zone_id` and `zone_channel_type` are available.

```
plate detected
  → find client_id via lists_db.find_client_by_plate()
  → zone_id = channel.get("zone_id")
  → zone_type = channel.get("zone_channel_type")   # 'entry', 'exit', or None

  BRANCH A: zone_id is None or zone_type is None
    → current behavior unchanged
    → insert_event(plate, ..., zone_id=None, time_entry=None)
    → _event_callback(event)

  BRANCH B: zone_type == 'entry'
    → determine zone_eligible = _resolve_zone_eligibility(channel, plate)
    → if zone_eligible:
        zone_fields = {"zone_id": zone_id, "time_entry": event_ts.isoformat()}
    → else:
        zone_fields = {}
    → insert_event(plate, ..., **zone_fields)
    → _event_callback(event)   [relay decision runs normally]

  BRANCH C: zone_type == 'exit'
    → determine zone_eligible = _resolve_zone_eligibility(channel, plate)
    → build relay_event = {channel_id, plate, direction, ...}  [for relay dispatch]
    → if zone_eligible:
        updated_id = events_db.find_active_entry_and_write_exit(plate, zone_id, time_exit_iso)
        if updated_id:
            relay_event["id"] = updated_id
        # If no open entry found: relay still fires, no DB write for exit fields
    → _event_callback(relay_event)   [relay decision runs normally]
    → DO NOT call insert_event()
```

### 4.3 `_resolve_zone_eligibility(channel, plate)` helper

This is a private method on `ChannelProcessor`. It mirrors the relay decision logic in `ControllerAutomationService._resolve_channel_controller_action`, but returns only the zone-write eligibility (True/False). It does NOT affect relay behavior — relay is controlled separately by the automation service.

```python
def _resolve_zone_eligibility(self, channel: dict, plate: str) -> bool:
    """
    Determine whether zone_id and time_entry/time_exit fields should be
    written to the event, based on list_filter_mode.
    Returns False for blacklisted plates regardless of mode.
    """
    if self._lists_db is None:
        return True  # no list db, treat as "all" mode

    if self._lists_db.plate_in_list_type(plate, "black"):
        return False

    mode = str(channel.get("list_filter_mode") or "all").strip().lower()
    if mode == "all":
        return True
    if mode == "whitelist":
        return self._lists_db.plate_in_list_type(plate, "white")
    if mode == "custom":
        list_ids = ControllerAutomationService._normalize_positive_int_ids(
            channel.get("list_filter_list_ids")
        )
        return self._lists_db.plate_in_lists(plate, list_ids)
    return True  # fallback
```

**Why replicate this logic instead of calling the automation service?**  
The automation service runs after the event callback and operates on the event dict. Zone eligibility must be known *before* the insert (or update). Extracting the logic to a shared utility function (e.g., `controllers/list_filter.py`) is a clean option if duplication is a concern, but for this scope it is clear inline.

### 4.4 Event callback for exit channels

For exit channels, `_event_callback` is called with a synthetic relay-trigger dict that has no `id` from a new insert (since no insert happened). The `ControllerAutomationService.dispatch_event()` only reads `channel_id`, `plate`, and `direction` from the event dict — these are always present. The `event_bus.publish()` call will also receive this dict; the frontend will display it as a live event notification. This is correct behavior — the operator sees that a vehicle passed the exit gate.

---

## 5. Controller / Relay Decision Flow

### What stays the same

`ControllerAutomationService._resolve_channel_controller_action()` is not modified. It reads `list_filter_mode`, checks the blacklist, checks whitelist or custom list membership, and returns `(allowed, reason)`. This is the relay gate, and it remains the sole arbiter of relay activation.

The direction filter in `dispatch_event()` is also unchanged.

### What changes for exit channels

For exit channels, the relay is still triggered by `_event_callback(relay_event)`. The relay dict passed must include:
- `channel_id` — used to look up channel config  
- `plate` — used for list membership checks  
- `direction` — used for direction filter  

All three are available from the detection result and channel context. No changes to `ControllerAutomationService` are needed.

### Relay behavior matrix

| Channel type | Zone eligible? | Blacklisted? | Direction match? | Relay fires? | Zone fields written? |
|---|---|---|---|---|---|
| No zone | — | No | Yes | Yes (per mode) | No |
| Entry | Yes | No | Yes | Yes (per mode) | Yes |
| Entry | No | No | Yes | Yes (per mode) | No |
| Entry | — | Yes | Any | No | No |
| Exit | Yes | No | Yes | Yes (per mode) | Yes (update) |
| Exit | No | No | Yes | Yes (per mode) | No |
| Exit | — | Yes | Any | No | No |

The relay column is governed entirely by `ControllerAutomationService`, which is already correct. Zone field eligibility is separately governed by `_resolve_zone_eligibility`.

---

## 6. API Changes

### 6.1 New router: `app/api/routers/zones.py`

Register in `app/api/main.py` alongside existing routers.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/zones` | List all zones (id, name, capacity, occupancy) |
| `POST` | `/api/zones` | Create zone |
| `GET` | `/api/zones/{zone_id}` | Get zone detail: name, capacity, occupancy (free spaces), list of assigned channels |
| `PUT` | `/api/zones/{zone_id}` | Update zone name/capacity |
| `DELETE` | `/api/zones/{zone_id}` | Delete zone (cascades channel zone_id/type to NULL) |

**`GET /api/zones`** response shape per zone:
```json
{
  "id": 1,
  "name": "Парковка А",
  "capacity": 50,
  "occupied": 12,
  "free": 38
}
```
`occupied` = `zone_db.get_zone_occupancy(id)`. Computed per-request, not stored.

**`DELETE /api/zones/{zone_id}`** — before delete, return affected channels in response body for confirmation at frontend level. The backend always performs the delete + cascade in one transaction when this endpoint is called. The frontend is responsible for showing the warning before calling the endpoint.

**`GET /api/zones/{zone_id}`** response adds:
```json
{
  "channels": [{"id": 3, "name": "Въезд 1"}, {"id": 4, "name": "Выезд 1"}]
}
```

### 6.2 Updated: `app/api/routers/events.py`

- All query responses must include the new fields: `zone_id`, `time_entry`, `time_exit`
- Remove `channel` (text) from response dicts
- Column renames in `fetch_journal_page` parameters: `before_ts` still works internally, just mapped to the renamed `time` column
- SSE stream events include the new fields (they come from the event dict built in the runtime)

### 6.3 Updated: `app/api/routers/channels.py`

`PUT /api/channels/{channel_id}/config` — validate `zone_id` field: if provided and non-null, verify the zone exists via `container.zone_db.get_zone(zone_id)`. Raise HTTP 400 if not found.

Add method to `AppContainer`:
```python
def validate_channel_zone_binding(self, payload: dict) -> None:
    zone_id = payload.get("zone_id")
    if zone_id is None:
        payload["zone_channel_type"] = None
        return
    if not self.zone_db.get_zone(int(zone_id)):
        raise HTTPException(status_code=400, detail=f"Зона #{zone_id} не найдена")
```

### 6.4 Updated: `app/api/schemas.py`

**New schemas:**

```python
class ZonePayload(BaseModel):
    name: str
    capacity: int = Field(default=0, ge=0)

class ZoneUpdatePayload(BaseModel):
    name: str
    capacity: int = Field(ge=0)
```

**Updated `ChannelConfigPayload`:**

```python
zone_id: Optional[int] = None
zone_channel_type: Optional[str] = Field(
    default=None,
    pattern="^(entry|exit)$"
)
```

`zone_channel_type` validator: if `zone_id` is None, `zone_channel_type` must also be None.

---

## 7. Frontend Changes

### 7.1 Overview of affected files

| File | Type | Change |
|---|---|---|
| `app/web/index.html` | HTML | Add Zones tab in sidebar under Observation group |
| `app/web/js/app.js` | JS | Register zones tab route, import zones module |
| `app/web/js/zones.js` | JS (new) | Full zones management UI |
| `app/web/js/channels.js` | JS | Add zone settings section to channel config form |
| `app/web/js/events.js` | JS | Show `time_entry`, `time_exit`, zone badge in live events |
| `app/web/js/journal.js` | JS | Show new event fields in journal table; update `channel` column to use name lookup |
| `app/web/js/api.js` | JS | Add zone API methods |

### 7.2 New tab: Zones

Location in sidebar: under the **Observation** group, after **Events**.

**`app/web/js/zones.js`** — module structure:

```
zones.js
  ├── loadZones()          → GET /api/zones
  ├── renderZoneList()     → display zone cards
  ├── openZoneSettings()   → show zone detail panel
  ├── createZone()         → POST /api/zones (name only, capacity optional)
  ├── updateZone()         → PUT /api/zones/{id}
  ├── deleteZone()         → pre-check channels via GET /api/zones/{id},
  │                          show confirmation modal listing affected channels,
  │                          then DELETE /api/zones/{id}
  └── renderOccupancy()    → display capacity / occupied / free
```

**Zone list card layout:**
```
┌─────────────────────────────────────┐
│ Парковка А                          │
│ Вместимость: 50  Занято: 12  Свободно: 38 │
│                        [⚙ Настройки] [✕ Удалить] │
└─────────────────────────────────────┘
```

**Delete flow:**
1. User clicks Delete  
2. Frontend calls `GET /api/zones/{id}` to get list of affected channels  
3. If any channels use this zone, show warning modal listing channel names  
4. On confirmation, call `DELETE /api/zones/{id}`  
5. For each affected channel shown, the backend has already cleared zone_id — frontend reloads channel list  

**Occupancy display:**  
Free spaces are derived server-side (`capacity - occupied`). Display as: `Свободно: N / Вместимость: M`.  
Note in UI that free spaces update in real time as vehicles enter/exit — but live update requires polling. For v1, use manual refresh or reload on tab activation.

### 7.3 Channel settings zone section

In `channels.js`, within the channel config form, add a **Зона** section below the Controller section:

```
[ Зона ─────────────────────────────── ]
  Зона:          [ dropdown / Без зоны ]
  Тип канала:    [ Въезд / Выезд / — ]
  Режим фильтра: (uses existing list_filter_mode — no change)
```

The zone dropdown loads from `GET /api/zones`.  
`Тип канала` is only enabled when a zone is selected.  
If zone is set to "Без зоны" (None), `zone_channel_type` is cleared.

### 7.4 Events and Journal display

**Live events (`events.js`):**  
- Add zone badge: if `zone_id > 0`, show zone name badge (requires mapping zone_id → name; load zone list on init)  
- Show `time_entry` or `time_exit` if present  

**Journal (`journal.js`):**  
- Remove `channel` (text) column — replace with channel name looked up from the channel list (already loaded in state)  
- Add optional columns: `Зона`, `Въезд`, `Выезд`  
- These columns can be toggled off by default to avoid clutter; add a column visibility toggle  

---

## 8. Zone Deletion and Reset Behavior

**Trigger:** `DELETE /api/zones/{zone_id}`

**Database operations (single transaction):**
1. `UPDATE channels SET zone_id = NULL, zone_channel_type = NULL WHERE zone_id = $1`
2. `DELETE FROM zones WHERE id = $1`

**What happens to existing events:**  
Events with `zone_id = {deleted_zone_id}` are **not modified**. They are historical records and must remain intact for audit. If a query filters by zone, it will simply find no matching channels anymore, but the events remain queryable by `zone_id` directly if needed.

**Frontend behavior:**  
After zone deletion, the channel list must be reloaded so affected channels show "no zone" in their config. The zones tab removes the deleted zone from the list.

**No orphan protection on zone_id in events:**  
Since events use `zone_id` as a denormalized value (no FK), no cascade is needed or appropriate. The value `0` already serves as the "exited" sentinel. Deleted zone IDs become references to a zone that no longer exists — the value is still meaningful as historical data (it was zone #3 when the vehicle entered).

---

## 9. Non-Zone Compatibility Behavior

**Invariant:** If `channel.zone_id IS NULL` or `channel.zone_channel_type IS NULL`, the channel behaves exactly as it does today, with no observable difference.

**Database level:**  
- `zone_id`, `time_entry`, `time_exit` are all nullable and default to NULL  
- No existing event query logic breaks; all new columns are additive  

**Runtime level:**  
`_run_channel()` checks `zone_id = channel.get("zone_id")` at the start of event processing. If None, it skips all zone branching and calls `insert_event()` with the same arguments as today, plus `zone_id=None, time_entry=None` (which are the default parameter values).

**API level:**  
The existing `ChannelConfigPayload` is extended with optional fields defaulting to None. Clients that do not send zone fields receive channels with zone fields as None — same as before.

**Frontend level:**  
`events.js` and `journal.js` check `if (event.zone_id && event.zone_id > 0)` before rendering zone UI elements. Journal column for zone is hidden by default.

---

## 10. Edge Cases and Risks

### 10.1 Exit with no matching entry event

**Scenario:** A vehicle exits through a zone-enabled exit channel, but no entry event exists for that plate in that zone (vehicle entered before the feature was enabled, or entry channel was down).

**Behavior:** `find_active_entry_and_write_exit()` returns None. No DB write happens for `time_exit`. The relay decision still proceeds via `_event_callback`. The operator sees the plate event in live view.

**Risk level:** Low. This is expected during initial deployment and after downtime.

### 10.2 Multiple open entries for the same plate

**Scenario:** The same plate passes an entry channel twice without an intervening exit. Both events exist with `time_exit IS NULL`.

**Behavior:** `find_active_entry_and_write_exit()` uses `ORDER BY time DESC LIMIT 1` — it closes the most recent open entry. The older entry remains open.

**Risk level:** Medium. This can cause the occupancy count to overcount. Accept for v1; document as known behavior. Future fix: on entry, check if a prior open entry exists for the plate in this zone and close it first.

### 10.3 `zone_id = 0` sentinel collision

**Scenario:** `zone_id = 0` means "exited." If a zone with `id = 0` were ever created, this would be ambiguous.

**Resolution:** `SERIAL` primary keys start at 1, never 0. The sentinel value 0 is safe.

### 10.4 `channel` column removal impact on exports

The existing `fetch_for_export` accepts a `channel` (text) filter parameter. After the column is removed, this filter must be removed or replaced with `channel_id`. The data export endpoint (`POST /api/data/export/bundle`) in `app/api/routers/data.py` must be updated to remove the `channel` text filter option.

**Risk level:** Medium. The export endpoint and `DataLifecycleService` need to be audited for any reference to the `channel` column name.

### 10.5 Rename of `timestamp` column breaks journal pagination

The cursor-based pagination in `fetch_journal_page` uses `(timestamp, id) < (%s, %s)`. This is a composite cursor and must be updated to use `(time, id) < (%s, %s)`.

The API parameters `before_ts` and `start_ts`/`end_ts` are parameter names in Python, not column names — they do not change. Only the SQL query strings change.

**Risk level:** Low. Mechanical rename; easy to miss in the export query since it has its own `WHERE` block. Audit every query string in the file.

### 10.6 SSE event dict for exit channels

For exit channels, `_event_callback` is called without a preceding `insert_event`. The event dict has no `id` field. The `EventBus.publish()` will broadcast this dict to SSE clients. The frontend `events.js` must not crash when `event.id` is undefined for exit-channel events.

**Resolution:** Set `event["id"] = updated_id or None` and guard in the frontend: `const eventId = event.id ?? null`.

### 10.7 Zone occupancy under load

`get_zone_occupancy()` runs a `COUNT(*)` query on every `GET /api/zones` call. Under high event volumes (many cameras, many plates), this count can become slow.

**For v1:** The index `idx_events_zone_active` makes this fast enough. If performance degrades, a materialized counter in the zones table is the upgrade path — but that requires update triggers or application-level counter increments. Defer until observed.

### 10.8 Direction filtering on exit channels

Exit channels can have a `controller_direction_filter`. In a physical exit lane, the expected direction is typically `RECEDING` (vehicle moving away from camera). If an operator sets the exit channel to filter by `APPROACHING`, no relay will fire. This is correct behavior — it is the operator's responsibility to configure the direction filter appropriately. No special handling needed.

### 10.9 Thread safety of zone eligibility lookup

`_resolve_zone_eligibility()` calls `self._lists_db.plate_in_list_type()` and `plate_in_lists()`, which open a database connection from the shared pool. These are called from the channel processing thread. This is identical to the existing `find_client_by_plate()` call already in the thread — the pool is thread-safe by design. No new concerns.

---

## 11. Phased Implementation Plan

Each phase is independently commitable and testable.

---

### Phase 1 — Database Schema Redesign ✅ COMPLETED

**Goal:** Clean schema with new events table, zones table, and zone columns on channels.  
**Touches:** `database/postgres/schema.sql`

**Tasks:**

1. ✅ Replace `database/postgres/schema.sql` with the new schema (Section 2.4)
2. Verify schema boots cleanly on a fresh database by running the app and checking startup logs

**Done when:** App starts, schema initializes without error, `\d events` in psql shows correct columns.

---

### Phase 2 — Events Repository Update ✅ COMPLETED

**Goal:** `PostgresEventDatabase` speaks the new schema.  
**Touches:** `database/postgres_event_repository.py`

**Tasks:**

1. ✅ Update `_to_dict`: remove `channel`, add `zone_id`, `time_entry`, `time_exit`; map column positions to new schema order
2. ✅ Update `insert_event`: remove `channel` parameter; add optional `zone_id`, `time_entry`
3. ✅ Update all SELECT query strings: `timestamp` → `time`; remove `channel` from column list; add new columns
4. ✅ Update `fetch_journal_page`: fix cursor `(timestamp, id)` → `(time, id)`, fix column list, fix filter for `channel` text → remove (keep `channel_id`)
5. ✅ Update `fetch_for_export`: remove `channel` text filter; update column list
6. ✅ Add `find_active_entry_and_write_exit(plate, zone_id, time_exit_iso)` method
7. ✅ Update `delete_before` to use `time` column
8. ✅ Update `fetch_last_plates_by_channel_ids` to use `time` column and new column list

**Done when:** All existing tests pass; manual check that insert and fetch return correct field names.

---

### Phase 3 — Channel Repository Update ✅ COMPLETED

**Goal:** Channels carry zone config in the database.  
**Touches:** `database/channel_repository.py`

**Tasks:**

1. ✅ Add `zone_id INTEGER, zone_channel_type TEXT` to `_SCHEMA` CREATE TABLE
2. ✅ Append `zone_id, zone_channel_type` to `_SELECT_COLS`
3. ✅ Update `_row_to_dict`: map positions 28, 29
4. ✅ Update `_normalize`: add zone_id and zone_channel_type normalization block (Section 3.3)
5. ✅ Update `create_channel` INSERT: add `zone_id, zone_channel_type` columns and values
6. ✅ Update `update_channel` UPDATE SET: add `zone_id=%s, zone_channel_type=%s`

**Done when:** Creating and updating a channel with `zone_id=1, zone_channel_type='entry'` persists and round-trips correctly.

---

### Phase 4 — Zones Repository ✅ COMPLETED

**Goal:** Full CRUD for zones table, including cascade-on-delete for channels.  
**Touches:** `database/zones_repository.py` (new file), `app/api/container.py`

**Tasks:**

1. ✅ Create `database/zones_repository.py` with `ZoneDatabase(PooledDatabase)` (Section 3.1)
2. ✅ Add `ZoneDatabase` to `AppContainer.build()` and `refresh_storage_clients()`
3. ✅ Wire `zone_db` into `ChannelProcessor` constructor and store as `self._zones_db`
4. ✅ Expose `zone_db` via `AppContainer` dataclass field

**Done when:** `ZoneDatabase.create_zone()`, `list_zones()`, `delete_zone()` work and channel cascade fires on zone delete.

---

### Phase 5 — Zones API Router ✅ COMPLETED

**Goal:** REST endpoints for zone management.  
**Touches:** `app/api/routers/zones.py` (new), `app/api/main.py`, `app/api/schemas.py`

**Tasks:**

1. ✅ Add `ZonePayload` and `ZoneUpdatePayload` to `schemas.py`
2. ✅ Create `app/api/routers/zones.py` with all endpoints (Section 6.1)
3. ✅ Register router in `app/api/main.py`
4. ✅ Add `validate_channel_zone_binding()` to `AppContainer` (Section 6.3)
5. ✅ Call zone validation in `put_channel_config` in `channels.py`
6. ✅ Add `zone_id: Optional[int]` and `zone_channel_type: Optional[str]` to `ChannelConfigPayload`

**Done when:** All zone endpoints return correct data; zone delete cascades channels in the DB; creating a channel with an invalid zone_id returns 400.

---

### Phase 6 — Zone-Aware Event Processing ✅ COMPLETED

**Goal:** Entry channels write zone fields; exit channels update existing events.  
**Touches:** `runtime/channel_runtime.py`, `controllers/service.py` (no change needed), `app/api/container.py`

**Tasks:**

1. ✅ Add `_resolve_zone_eligibility(channel, plate)` method to `ChannelProcessor` (Section 4.3)
2. ✅ Modify the event-creation block in `_run_channel()`:
   - Read `zone_id` and `zone_channel_type` from `channel` dict
   - Branch A (no zone): pass through unchanged
   - Branch B (entry channel): compute eligibility; include `zone_id` and `time_entry` in `insert_event` if eligible
   - Branch C (exit channel): compute eligibility; if eligible, call `find_active_entry_and_write_exit`; build relay_event dict; call `_event_callback(relay_event)` without calling `insert_event`
3. ✅ Ensure relay_event dict for exit channels always has `channel_id`, `plate`, `direction`
4. ✅ Add `event.get("id")` guard in the callback path (may be None for exit channels)

**Done when:** 
- A channel with no zone creates events identically to before
- An entry channel with mode "all" writes `zone_id` and `time_entry` on every non-blacklisted plate
- An exit channel finds the open entry event, writes `time_exit` and sets `zone_id = 0`, and the relay fires
- An entry channel with mode "whitelist" only writes zone fields for whitelisted plates but still creates the event

---

### Phase 7 — Export and Lifecycle Cleanup ✅ COMPLETED

**Goal:** Ensure `fetch_for_export`, data lifecycle, and backup are consistent with the new schema.  
**Touches:** `app/api/routers/data.py`, `app/shared/data_lifecycle.py`

**Tasks:**

1. ✅ Audit `app/api/routers/data.py` for any reference to `channel` text column or `timestamp` column
2. ✅ Update `ExportBundlePayload` if it has a `channel` text filter — replace with `channel_id`
3. ✅ Audit `app/shared/data_lifecycle.py` for column references in `delete_before` or related queries
4. ✅ Update CSV export column headers to reflect `time`, `zone_id`, `time_entry`, `time_exit`; remove `channel` (text)

**Done when:** Export bundle generates a CSV with correct columns; retention delete still works.

---

### Phase 8 — Frontend: Zones Tab ✅ COMPLETED

**Goal:** Operators can create, view, configure, and delete zones.  
**Touches:** `app/web/js/zones.js` (new), `app/web/index.html`, `app/web/js/app.js`, `app/web/js/api.js`

**Tasks:**

1. ✅ Add zone API methods to `api.js`: `getZones()`, `createZone()`, `getZone(id)`, `updateZone(id, data)`, `deleteZone(id)`
2. ✅ Create `app/web/js/zones.js` with zone list, create, settings panel, delete-with-warning flow (Section 7.2)
3. ✅ Add Zones entry to sidebar in `index.html`
4. ✅ Register zones tab route in `app.js`

**Done when:** Zones tab loads, zone create/delete works, zone settings panel shows name/capacity/occupancy/channels.

---

### Phase 9 — Frontend: Channel Zone Settings ✅

**Goal:** Operators can assign a zone and channel type to a channel from the channel config form.  
**Touches:** `app/web/js/channels.js`

**Tasks:**

1. Load zone list on channel config form open
2. Add "Зона" dropdown (populated from zone list, plus "Без зоны" option)
3. Add "Тип канала" select (Въезд / Выезд), enabled only when a zone is selected
4. On save, include `zone_id` and `zone_channel_type` in the config payload
5. On load, populate the dropdowns from the current channel config

**Done when:** A channel can be assigned to zone with type "entry" or "exit", saved, and reloaded correctly.

---

### Phase 10 — Frontend: Events and Journal Updates ✅

**Goal:** Live events and journal reflect zone tracking fields.  
**Touches:** `app/web/js/events.js`, `app/web/js/journal.js`

**Tasks:**

1. `events.js`: show zone badge for events where `zone_id > 0`; show `time_entry`/`time_exit` if present
2. `events.js`: guard against missing `event.id` (exit-channel events may have no id)
3. `journal.js`: replace `channel` (text) column with channel name from channel list
4. `journal.js`: add optional `Зона`, `Въезд`, `Выезд` columns (hidden by default, togglable)
5. `journal.js`: update pagination cursor to use `time` instead of `timestamp` key

**Done when:** Live event row shows zone name badge; journal table renders without errors; zone columns can be toggled visible.

---

## 12. Testing Plan ✅

### Unit tests

**`tests/test_zones_repository.py`** — new file

- `test_create_zone` — create returns valid id; list returns the zone
- `test_update_zone` — name and capacity update correctly
- `test_delete_zone_cascades_channels` — after zone delete, all channels with that zone_id have zone_id=NULL and zone_channel_type=NULL
- `test_get_zone_occupancy_empty` — newly created zone returns 0 occupancy
- `test_get_zone_occupancy_counts_only_open_entries` — events with time_exit=NULL count; events with time_exit set do not count

**`tests/test_events_repository_zones.py`** — new file (or extend `test_events_repository.py`)

- `test_insert_event_with_zone_fields` — zone_id and time_entry round-trip correctly
- `test_insert_event_no_zone_fields_defaults_null` — zone fields are NULL by default
- `test_find_active_entry_and_write_exit_found` — most recent open entry for plate+zone gets time_exit and zone_id=0
- `test_find_active_entry_and_write_exit_not_found` — returns None when no open entry exists
- `test_find_active_entry_targets_most_recent` — two open entries for same plate; exit closes only the most recent
- `test_fetch_journal_page_uses_time_column` — pagination cursor works with renamed column
- `test_to_dict_no_channel_text_field` — response dict has no `channel` key

**`tests/test_channel_repository_zones.py`** — new file (or extend existing)

- `test_create_channel_with_zone` — zone_id and zone_channel_type persist
- `test_normalize_clears_zone_type_when_no_zone` — if zone_id=None, zone_channel_type forced to None
- `test_normalize_rejects_invalid_zone_type` — "entry" and "exit" valid; anything else becomes None

**`tests/test_zone_eligibility.py`** — new file

- `test_all_mode_non_blacklisted_is_eligible`
- `test_all_mode_blacklisted_is_not_eligible`
- `test_whitelist_mode_whitelisted_is_eligible`
- `test_whitelist_mode_not_in_whitelist_not_eligible`
- `test_custom_mode_in_list_is_eligible`
- `test_custom_mode_not_in_list_not_eligible`

### Integration tests (manual or pytest with real DB)

- **Entry flow, mode "all":** Plate recognized on entry channel → event created with zone_id and time_entry
- **Entry flow, mode "whitelist":** Whitelisted plate → zone fields written; non-whitelisted plate → event created but no zone fields
- **Exit flow, mode "all":** Plate recognized on exit channel → existing open entry updated; no new event created
- **Exit flow, no open entry:** Plate recognized on exit channel with no prior open entry → no DB write, relay still fires
- **Zone delete cascade:** Delete zone → channel_db.get_channel(id) returns zone_id=None, zone_channel_type=None
- **Non-zone channel:** Channel with no zone assigned → event has zone_id=NULL, time_entry=NULL; all relay logic unchanged

### Regression checklist

- [ ] Existing channels without zone settings continue to create events normally
- [ ] Controller relay fires correctly for non-zone channels (whitelist, all, custom modes)
- [ ] Journal pagination still works (cursor-based, now using `time` column)
- [ ] Export bundle generates correct CSV (no `channel` text column; `time` column correct)
- [ ] SSE stream delivers events with `id` for entry-channel events; no crash for exit-channel events
- [ ] Settings save/restore (backup/restore) still works — does not touch events table

---

## 13. Documentation Update Plan ✅ COMPLETED

### `README.md` ✅
- Added "Режим парковочных зон" to Ключевые возможности
- Added link to `docs/zones.md` in the documentation table

### `docs/endpoints.md` ✅
- Added Zones section with all 5 endpoints

### `docs/architecture.md` ✅
- Added zones to postgres storage list
- Extended Main Runtime Flow with zone branch (steps 5a/5b for entry/exit)
- Added `zone_id = 0` sentinel explanation note
- Added link to zones.md in Related Documents

### `docs/modules.md` ✅
- Added `database/zones_repository.py`
- Added `app/api/routers/zones.py`
- Added `app/web/js/zones.js`
- Extended `api.js` description with zone API methods
- Extended tests section with 4 new zone test files

### `docs/project-structure.md` ✅
- Added `zones_repository.py` to database directory
- Added `zones.js` to JS directory
- Added 4 zone test files to tests directory

### `docs/setup.md` ✅
- Updated events table fields (timestamp→time, removed channel text, added zone_id/time_entry/time_exit)
- Added zones table
- Added zone_id sentinel explanation
- Updated index description

### New doc: `docs/zones.md` ✅
Created dedicated zones documentation covering:
- Concept and channel type explanation
- Setup walkthrough (create zone → assign channels)
- Entry and exit event flow
- Occupancy display
- `zone_id` field semantics
- Zone deletion behavior
- Known limitations
- API reference

---

## Summary

| Item | Count |
|---|---|
| New files | `database/zones_repository.py`, `app/api/routers/zones.py`, `app/web/js/zones.js` |
| Modified backend files | 7 (`schema.sql`, `postgres_event_repository.py`, `channel_repository.py`, `container.py`, `channel_runtime.py`, `schemas.py`, `data.py`) |
| Modified frontend files | 5 (`index.html`, `app.js`, `api.js`, `channels.js`, `events.js`, `journal.js`) |
| New test files | 4 |
| Implementation phases | 10 |
| Documentation files | 6 updated + 1 new |

**Invariant preserved:** Channels without a zone assignment behave identically to the current system in every observable way — event creation, relay activation, list filtering, direction filtering, API responses, and frontend display.
