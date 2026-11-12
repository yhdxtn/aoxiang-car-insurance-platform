"""Encrypted technical request journal. MySQL in Java remains the business source."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class RequestConflict(ValueError):
    pass


class Ledger:
    def __init__(self, path: Path, key: bytes):
        self.path = path
        self.key = key
        self.cipher = AESGCM(key)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._process_lock = open(str(path) + ".lock", "a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self._process_lock.seek(0)
                if self._process_lock.read(1) == b"":
                    self._process_lock.write(b"0")
                    self._process_lock.flush()
                self._process_lock.seek(0)
                msvcrt.locking(self._process_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            self._process_lock.close()
            raise RuntimeError("该网关账本已有运行实例。请保持单实例，不要启用多个 workers。") from None
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS request_journal (
                request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL, payload BLOB, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            check = hmac.new(key, b"taikang-mini-ledger-key-v1", hashlib.sha256).hexdigest()
            stored = db.execute("SELECT value FROM metadata WHERE name='key_check'").fetchone()
            if stored and not hmac.compare_digest(stored[0], check):
                self.close()
                raise RuntimeError("网关账本加密密钥不匹配；请恢复原密钥，禁止丢弃去重账本重报。")
            db.execute("INSERT OR IGNORE INTO metadata(name,value) VALUES ('key_check',?)", (check,))
        if os.name != "nt":
            path.chmod(0o600)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute("PRAGMA synchronous=FULL")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def fingerprint(self, payload: dict):
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return hmac.new(self.key, encoded, hashlib.sha256).hexdigest()

    def begin(self, request_id: str, payload: dict):
        fingerprint = self.fingerprint(payload)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT fingerprint,state,payload FROM request_journal WHERE request_id=?",
                             (request_id,)).fetchone()
            if row:
                if not hmac.compare_digest(row[0], fingerprint):
                    raise RequestConflict("同一请求编号不能提交不同车辆或方案")
                if row[1] == "COMPLETED":
                    packed = bytes(row[2])
                    decoded = self.cipher.decrypt(packed[:12], packed[12:], request_id.encode())
                    return json.loads(decoded)["response"]
                return {"status": "OUTCOME_UNKNOWN", "insurer": "TAIKANG", "demo": False,
                        "message": "本笔请求已登记但结果未确认，请客服核查原笔；系统未自动重报。"}
            db.execute("INSERT INTO request_journal(request_id,fingerprint,state) VALUES (?,?,'STARTED')",
                       (request_id, fingerprint))
        return None

    def complete(self, request_id: str, response: dict, evidence: dict | None = None):
        nonce = os.urandom(12)
        encoded = json.dumps({"response": response, "evidence": evidence or {}},
                             ensure_ascii=False, separators=(",", ":")).encode()
        encrypted = nonce + self.cipher.encrypt(nonce, encoded, request_id.encode())
        with self.connect() as db:
            changed = db.execute("UPDATE request_journal SET state='COMPLETED',payload=? "
                                 "WHERE request_id=? AND state='STARTED'", (encrypted, request_id)).rowcount
            if changed != 1:
                raise RuntimeError("技术请求状态发生冲突；未覆盖原结果")

    def close(self):
        if not self._process_lock.closed:
            self._process_lock.close()
