-- Spend per day, counted from each answer's token usage.
CREATE TABLE IF NOT EXISTS spend (day TEXT PRIMARY KEY, usd REAL NOT NULL, questions INTEGER NOT NULL);
-- Questions per visitor per hour; the key is a hash, never the raw IP or user id.
CREATE TABLE IF NOT EXISTS hits (key TEXT PRIMARY KEY, n INTEGER NOT NULL);
