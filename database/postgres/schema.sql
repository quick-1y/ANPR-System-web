CREATE TABLE IF NOT EXISTS events (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    channel_id INTEGER,
    channel TEXT NOT NULL,
    plate TEXT NOT NULL,
    plate_display TEXT,
    country TEXT,
    confidence DOUBLE PRECISION,
    source TEXT,
    frame_path TEXT,
    plate_path TEXT,
    direction TEXT,
    client_id BIGINT
);

-- Migration: add plate_display column to existing installations.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'events' AND column_name = 'plate_display'
    ) THEN
        ALTER TABLE events ADD COLUMN plate_display TEXT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel_id ON events(channel_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel ON events(channel);
CREATE INDEX IF NOT EXISTS idx_events_plate ON events(plate);
CREATE INDEX IF NOT EXISTS idx_events_ts_id_desc ON events(timestamp DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_channel_id_ts_id_desc ON events(channel_id, timestamp DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_events_client_id ON events(client_id) WHERE client_id IS NOT NULL;

-- ── Users (auth) ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                  BIGSERIAL PRIMARY KEY,
    login               TEXT NOT NULL UNIQUE,
    password            TEXT NOT NULL,
    role                TEXT NOT NULL DEFAULT 'operator',
    permissions         JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    password_changed_at TIMESTAMPTZ DEFAULT NULL
);

-- Migration: add password_changed_at column to existing installations.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'password_changed_at'
    ) THEN
        ALTER TABLE users ADD COLUMN password_changed_at TIMESTAMPTZ DEFAULT NULL;
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users(login);
