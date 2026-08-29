ALTER TABLE messages ADD COLUMN event_id TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_event_id ON messages (event_id);
