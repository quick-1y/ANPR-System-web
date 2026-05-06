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
