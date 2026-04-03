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
    direction TEXT
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

-- ── Users (auth) ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          BIGSERIAL PRIMARY KEY,
    login       TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL,
    role        TEXT NOT NULL DEFAULT 'operator',
    permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login ON users(login);
