CREATE TABLE organizations (
 id VARCHAR(36) PRIMARY KEY, name VARCHAR(100) NOT NULL, parent_id VARCHAR(36), depth INT NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMP(6) NOT NULL,
 CONSTRAINT fk_org_parent FOREIGN KEY (parent_id) REFERENCES organizations(id)
);
CREATE INDEX ix_org_parent ON organizations(parent_id);
CREATE TABLE users (
 id VARCHAR(36) PRIMARY KEY, username VARCHAR(100) NOT NULL UNIQUE, password_hash VARCHAR(100),
 openid_hash VARCHAR(64) UNIQUE, name VARCHAR(100) NOT NULL, role VARCHAR(20) NOT NULL, org_id VARCHAR(36) NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT TRUE, points BIGINT NOT NULL DEFAULT 0, invite_code VARCHAR(32) UNIQUE,
 created_at TIMESTAMP(6) NOT NULL, CONSTRAINT fk_user_org FOREIGN KEY (org_id) REFERENCES organizations(id)
);
CREATE INDEX ix_users_org ON users(org_id,role);
CREATE TABLE auth_tokens (
 token_hash VARCHAR(64) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, expires_at TIMESTAMP(6) NOT NULL,
 created_at TIMESTAMP(6) NOT NULL, CONSTRAINT fk_token_user FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX ix_tokens_user ON auth_tokens(user_id);
CREATE TABLE quote_sessions (
 id VARCHAR(36) PRIMARY KEY, owner_id VARCHAR(36) NOT NULL, org_id VARCHAR(36) NOT NULL,
 vehicle_type VARCHAR(20) NOT NULL, status VARCHAR(20) NOT NULL, stage INT NOT NULL DEFAULT 1,
 assigned_to VARCHAR(36), vehicle_data LONGTEXT NOT NULL, vehicle_revision INT NOT NULL DEFAULT 0,
 message_seq BIGINT NOT NULL DEFAULT 0, order_id VARCHAR(36), created_at TIMESTAMP(6) NOT NULL,
 updated_at TIMESTAMP(6) NOT NULL, CONSTRAINT fk_session_owner FOREIGN KEY (owner_id) REFERENCES users(id),
 CONSTRAINT fk_session_org FOREIGN KEY (org_id) REFERENCES organizations(id),
 CONSTRAINT fk_session_agent FOREIGN KEY (assigned_to) REFERENCES users(id)
);
CREATE INDEX ix_session_scope ON quote_sessions(org_id,status,updated_at);
CREATE INDEX ix_session_owner ON quote_sessions(owner_id,created_at);
CREATE TABLE private_files (
 id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36) NOT NULL, uploader_id VARCHAR(36) NOT NULL,
 file_name VARCHAR(200) NOT NULL, mime_type VARCHAR(64) NOT NULL, file_size BIGINT NOT NULL,
 storage_name VARCHAR(80) NOT NULL, source VARCHAR(20) NOT NULL, document_type VARCHAR(30) NOT NULL,
 created_at TIMESTAMP(6) NOT NULL, CONSTRAINT fk_file_session FOREIGN KEY (session_id) REFERENCES quote_sessions(id)
);
CREATE INDEX ix_files_session ON private_files(session_id);
CREATE TABLE chat_messages (
 id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36) NOT NULL, seq BIGINT NOT NULL,
 sender_id VARCHAR(36) NOT NULL, message_role VARCHAR(20) NOT NULL, content_data LONGTEXT NOT NULL,
 file_id VARCHAR(36), client_message_id VARCHAR(100) NOT NULL, created_at TIMESTAMP(6) NOT NULL,
 CONSTRAINT uq_msg_seq UNIQUE(session_id,seq), CONSTRAINT uq_msg_key UNIQUE(session_id,sender_id,client_message_id),
 CONSTRAINT fk_msg_session FOREIGN KEY (session_id) REFERENCES quote_sessions(id),
 CONSTRAINT fk_msg_file FOREIGN KEY (file_id) REFERENCES private_files(id)
);
CREATE TABLE quotes (
 id VARCHAR(36) PRIMARY KEY, session_id VARCHAR(36) NOT NULL, revision INT NOT NULL,
 vehicle_revision INT NOT NULL, idempotency_key VARCHAR(100) NOT NULL, request_hash VARCHAR(64) NOT NULL,
 status VARCHAR(30) NOT NULL, plan VARCHAR(20) NOT NULL, snapshot_data LONGTEXT NOT NULL,
 result_data LONGTEXT NOT NULL, valid_until TIMESTAMP(6), deadline_at TIMESTAMP(6) NOT NULL,
 demo BOOLEAN NOT NULL, created_at TIMESTAMP(6) NOT NULL,
 CONSTRAINT uq_quote_key UNIQUE(session_id,idempotency_key), CONSTRAINT uq_quote_revision UNIQUE(session_id,revision),
 CONSTRAINT fk_quote_session FOREIGN KEY (session_id) REFERENCES quote_sessions(id)
);
CREATE INDEX ix_quote_status ON quotes(status,deadline_at);
CREATE TABLE policies (
 id VARCHAR(36) PRIMARY KEY, title VARCHAR(120) NOT NULL, content_text LONGTEXT NOT NULL,
 org_id VARCHAR(36) NOT NULL, parent_policy_id VARCHAR(36), version INT NOT NULL,
 rate DECIMAL(8,4) NOT NULL, enabled BOOLEAN NOT NULL, effective_from DATE NOT NULL, effective_to DATE,
 vehicle_type VARCHAR(20) NOT NULL, created_by VARCHAR(36) NOT NULL, created_at TIMESTAMP(6) NOT NULL,
 CONSTRAINT uq_policy_version UNIQUE(org_id,vehicle_type,version),
 CONSTRAINT fk_policy_org FOREIGN KEY (org_id) REFERENCES organizations(id),
 CONSTRAINT fk_policy_parent FOREIGN KEY (parent_policy_id) REFERENCES policies(id)
);
CREATE INDEX ix_policy_scope ON policies(org_id,vehicle_type,effective_from);
CREATE TABLE insurance_orders (
 id VARCHAR(36) PRIMARY KEY, order_no VARCHAR(40) NOT NULL UNIQUE, session_id VARCHAR(36) NOT NULL UNIQUE,
 owner_id VARCHAR(36) NOT NULL, org_id VARCHAR(36) NOT NULL, quote_id VARCHAR(36) UNIQUE,
 idempotency_key VARCHAR(100) NOT NULL, request_hash VARCHAR(64) NOT NULL,
 vehicle_type VARCHAR(20) NOT NULL, status VARCHAR(30) NOT NULL, total_premium DECIMAL(16,2) NOT NULL, premium_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
 vehicle_data LONGTEXT NOT NULL, policy_no VARCHAR(100), policy_id VARCHAR(36), commission_rate DECIMAL(8,4) NOT NULL,
 demo BOOLEAN NOT NULL, created_at TIMESTAMP(6) NOT NULL, updated_at TIMESTAMP(6) NOT NULL,
 CONSTRAINT fk_order_session FOREIGN KEY (session_id) REFERENCES quote_sessions(id),
 CONSTRAINT fk_order_quote FOREIGN KEY (quote_id) REFERENCES quotes(id),
 CONSTRAINT fk_order_policy FOREIGN KEY (policy_id) REFERENCES policies(id)
);
CREATE INDEX ix_order_scope ON insurance_orders(org_id,status,created_at);
CREATE INDEX ix_order_owner ON insurance_orders(owner_id,created_at);
CREATE TABLE order_history (
 id VARCHAR(36) PRIMARY KEY, order_id VARCHAR(36) NOT NULL, status VARCHAR(30) NOT NULL,
 note_data LONGTEXT NOT NULL, actor_id VARCHAR(36) NOT NULL, created_at TIMESTAMP(6) NOT NULL,
 CONSTRAINT fk_history_order FOREIGN KEY (order_id) REFERENCES insurance_orders(id)
);
CREATE INDEX ix_history_order ON order_history(order_id,created_at);
CREATE TABLE customers (
 id VARCHAR(36) PRIMARY KEY, source_session_id VARCHAR(36) UNIQUE, owner_id VARCHAR(36) NOT NULL, org_id VARCHAR(36) NOT NULL,
 details_data LONGTEXT NOT NULL, created_at TIMESTAMP(6) NOT NULL, updated_at TIMESTAMP(6) NOT NULL,
 CONSTRAINT fk_customer_owner FOREIGN KEY (owner_id) REFERENCES users(id)
);
CREATE INDEX ix_customer_scope ON customers(org_id,owner_id);
CREATE TABLE points_ledger (
 id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, delta BIGINT NOT NULL,
 idempotency_key VARCHAR(100) NOT NULL, request_hash VARCHAR(64) NOT NULL, balance_after BIGINT NOT NULL,
 reason VARCHAR(500) NOT NULL, actor_id VARCHAR(36) NOT NULL, created_at TIMESTAMP(6) NOT NULL,
 CONSTRAINT uq_points_key UNIQUE(actor_id,idempotency_key),
 CONSTRAINT fk_points_user FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX ix_points_user ON points_ledger(user_id,created_at);
CREATE TABLE audit_logs (
 id VARCHAR(36) PRIMARY KEY, actor_id VARCHAR(36) NOT NULL, action VARCHAR(80) NOT NULL,
 target_id VARCHAR(100) NOT NULL, summary VARCHAR(500) NOT NULL, created_at TIMESTAMP(6) NOT NULL
);
CREATE INDEX ix_audit_date ON audit_logs(created_at);
CREATE TABLE app_metadata (meta_key VARCHAR(100) PRIMARY KEY,meta_value VARCHAR(500) NOT NULL);
