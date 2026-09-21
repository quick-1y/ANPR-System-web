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
    channel_id_entry INTEGER,
    channel_id_exit  INTEGER,
    plate            TEXT         NOT NULL,
    plate_display    TEXT,
    country          TEXT,
    confidence       DOUBLE PRECISION,
    source           TEXT,
    frame_path_entry TEXT,
    plate_path_entry TEXT,
    frame_path_exit  TEXT,
    plate_path_exit  TEXT,
    direction        TEXT,
    client_id     BIGINT,
    zone_id       INTEGER,
    time_entry    TIMESTAMPTZ,
    time_exit     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_events_plate
    ON events(plate);
CREATE INDEX IF NOT EXISTS idx_events_time_id_desc
    ON events(time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel_id_entry_time_id_desc
    ON events(channel_id_entry, time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel_id_exit_time_id_desc
    ON events(channel_id_exit, time DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_client_id
    ON events(client_id) WHERE client_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_zone_active
    ON events(zone_id) WHERE zone_id IS NOT NULL AND zone_id > 0 AND time_exit IS NULL;
CREATE INDEX IF NOT EXISTS idx_events_plate_zone_open
    ON events(plate, zone_id, time DESC)
    WHERE zone_id > 0 AND time_exit IS NULL;

-- ── Channels ─────────────────────────────────────────────────────────
-- Mirrors ChannelDatabase._SCHEMA (lazy bootstrap); tests/test_schema_sync.py
-- fails when the two drift apart.
CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    roi_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    region JSONB NOT NULL DEFAULT '{"unit":"px","points":[]}'::jsonb,
    best_shots INTEGER NOT NULL DEFAULT 3,
    cooldown_seconds INTEGER NOT NULL DEFAULT 5,
    ocr_min_confidence DOUBLE PRECISION NOT NULL DEFAULT 0.6,
    max_ocr_attempts INTEGER NOT NULL DEFAULT 15,
    max_consecutive_empty_ocr INTEGER NOT NULL DEFAULT 5,
    direction JSONB NOT NULL DEFAULT '{}'::jsonb,
    detection_mode TEXT NOT NULL DEFAULT 'motion',
    detector_frame_stride INTEGER NOT NULL DEFAULT 2,
    adaptive_stride_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    preview_fps_limit INTEGER NOT NULL DEFAULT 5,
    motion_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.01,
    motion_frame_stride INTEGER NOT NULL DEFAULT 1,
    motion_activation_frames INTEGER NOT NULL DEFAULT 3,
    motion_release_frames INTEGER NOT NULL DEFAULT 100,
    size_filter_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    min_plate_size JSONB NOT NULL DEFAULT '{"width":80,"height":20}'::jsonb,
    max_plate_size JSONB NOT NULL DEFAULT '{"width":400,"height":100}'::jsonb,
    controller_id INTEGER,
    controller_relay INTEGER NOT NULL DEFAULT 0,
    controller_direction_filter TEXT NOT NULL DEFAULT 'both',
    list_filter_mode TEXT NOT NULL DEFAULT 'all',
    list_filter_list_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    zone_before_id INTEGER,
    zone_after_id INTEGER,
    zone_channel_type TEXT
);

-- ── Controllers ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS controllers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'DTWONDER2CH',
    address TEXT NOT NULL DEFAULT '',
    password TEXT NOT NULL DEFAULT '0',
    relays JSONB NOT NULL DEFAULT '[{"mode":"pulse","timer_seconds":1,"hotkey":""},{"mode":"pulse","timer_seconds":1,"hotkey":""}]'::jsonb
);

-- ── Lists and clients ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS lists (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS clients (
    id BIGSERIAL PRIMARY KEY,
    list_id BIGINT REFERENCES lists(id) ON DELETE SET NULL,
    plate TEXT NOT NULL,
    plate_normalized TEXT NOT NULL,
    last_name TEXT NOT NULL DEFAULT '',
    first_name TEXT NOT NULL DEFAULT '',
    middle_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    car TEXT NOT NULL DEFAULT '',
    comment TEXT NOT NULL DEFAULT '',
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_lists_type ON lists(type);
CREATE INDEX IF NOT EXISTS idx_clients_plate ON clients(plate_normalized);
CREATE INDEX IF NOT EXISTS idx_clients_list ON clients(list_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_list_plate ON clients(list_id, plate_normalized) WHERE is_deleted = FALSE;

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
ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb;

-- ── Application settings (class A, roadmap 4.6) ──────────────────────
-- One row per leaf key. A missing key means "registry default", so the
-- table starts empty and needs no seeding.
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT        PRIMARY KEY,
    value      JSONB       NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by BIGINT      REFERENCES users(id) ON DELETE SET NULL
);

-- Revision counter: every write bumps it, so processes (api, retention
-- worker) can invalidate their settings cache by polling one row.
CREATE TABLE IF NOT EXISTS app_settings_revision (
    id         SMALLINT    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    revision   BIGINT      NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO app_settings_revision (id) VALUES (1) ON CONFLICT DO NOTHING;
