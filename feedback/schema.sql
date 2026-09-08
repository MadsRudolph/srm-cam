-- One row per submitted form. The answers stay as the JSON the form sent,
-- so adding a question never needs a migration; the few columns that are
-- worth filtering on are lifted out.
CREATE TABLE IF NOT EXISTS responses (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at TEXT    NOT NULL,          -- ISO 8601, UTC
  tag         TEXT,                      -- the ?for= value on the link, if any
  form_version INTEGER NOT NULL DEFAULT 1,
  fix_one     TEXT,                      -- the one required answer
  recommend   INTEGER,                   -- 1..5
  result      TEXT,                      -- usable board: first / second / ...
  answers     TEXT    NOT NULL,          -- full JSON payload
  ip_hash     TEXT,                      -- sha256 of ip + day, for rate limiting only
  user_agent  TEXT
);
CREATE INDEX IF NOT EXISTS responses_received ON responses (received_at);
CREATE INDEX IF NOT EXISTS responses_ip_hash ON responses (ip_hash);
