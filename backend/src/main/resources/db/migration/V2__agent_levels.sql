ALTER TABLE users ADD COLUMN agent_level INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN parent_agent_id VARCHAR(36);

-- Existing AGENT accounts are the first-level agents in the original schema.
UPDATE users SET agent_level = 1 WHERE role = 'AGENT' AND agent_level = 0;

ALTER TABLE users
  ADD CONSTRAINT fk_user_parent_agent FOREIGN KEY (parent_agent_id) REFERENCES users(id);
CREATE INDEX ix_users_parent_agent ON users(parent_agent_id);
