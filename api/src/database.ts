import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { randomBytes, randomUUID } from "node:crypto";
import { DatabaseSync } from "node:sqlite";

import { incrementLoginCodeCounter, loginCodeFromCounter, tokenDigest } from "./crypto.js";
import { conflict, forbidden, notFound, unavailable } from "./errors.js";

export type ServerRole = "owner" | "admin" | "editor" | "viewer";

export interface UserRecord {
  id: string;
  username: string;
  systemRole: "owner" | "user";
  passwordHash: string;
  createdAt: number;
  disabledAt: number | null;
}

export interface SessionRecord {
  id: string;
  userId: string;
  username: string;
  systemRole: "owner" | "user";
  csrfHash: string;
  expiresAt: number;
}

export interface ServerRecord {
  id: string;
  instanceId: string;
  name: string;
  pluginVersion: string;
  protocolVersion: number;
  createdAt: number;
  lastSeenAt: number | null;
  revokedAt: number | null;
}

export interface ServerListRecord extends ServerRecord {
  role: ServerRole;
}

export interface LegacyServerRecord extends ServerRecord {
  legacyUserId: string;
  legacyUsername: string;
}

export interface AuditRecord {
  id: number;
  actorUserId: string | null;
  actorUsername: string | null;
  serverId: string | null;
  action: string;
  target: string | null;
  outcome: string;
  createdAt: number;
}

interface Row {
  [column: string]: unknown;
}

type AccountTarget = { userId: string } | { username: string; passwordHash: string };

const MIGRATION = `
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at INTEGER NOT NULL
) STRICT;

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL COLLATE NOCASE UNIQUE,
  system_role TEXT NOT NULL CHECK(system_role IN ('owner', 'user')),
  password_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  disabled_at INTEGER
) STRICT;

CREATE TABLE IF NOT EXISTS web_sessions (
  id TEXT PRIMARY KEY,
  token_hash TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS web_sessions_expiry ON web_sessions(expires_at);

CREATE TABLE IF NOT EXISTS pairing_codes (
  id TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE,
  created_by TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  consumed_at INTEGER
) STRICT;
CREATE INDEX IF NOT EXISTS pairing_codes_expiry ON pairing_codes(expires_at);

CREATE TABLE IF NOT EXISTS login_codes (
  id TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE,
  server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  consumed_at INTEGER
) STRICT;
CREATE INDEX IF NOT EXISTS login_codes_expiry ON login_codes(expires_at);

CREATE TABLE IF NOT EXISTS servers (
  id TEXT PRIMARY KEY,
  instance_id TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  plugin_version TEXT NOT NULL,
  protocol_version INTEGER NOT NULL,
  created_at INTEGER NOT NULL,
  last_seen_at INTEGER,
  revoked_at INTEGER
) STRICT;

CREATE TABLE IF NOT EXISTS server_memberships (
  server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('owner', 'admin', 'editor', 'viewer')),
  created_at INTEGER NOT NULL,
  PRIMARY KEY(server_id, user_id)
) STRICT;

CREATE TABLE IF NOT EXISTS server_claim_codes (
  id TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE,
  server_id TEXT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  consumed_at INTEGER
) STRICT;
CREATE INDEX IF NOT EXISTS server_claim_codes_expiry ON server_claim_codes(expires_at);

CREATE TABLE IF NOT EXISTS login_code_issuer_state (
  id INTEGER PRIMARY KEY CHECK(id = 1),
  next_counter BLOB NOT NULL CHECK(typeof(next_counter) = 'blob' AND length(next_counter) = 10),
  key_material BLOB NOT NULL CHECK(typeof(key_material) = 'blob' AND length(key_material) = 32),
  exhausted INTEGER NOT NULL CHECK(exhausted IN (0, 1)),
  created_at INTEGER NOT NULL
) STRICT;

UPDATE login_codes
SET consumed_at = COALESCE(consumed_at, created_at)
WHERE code_hash IN (SELECT code_hash FROM server_claim_codes);
UPDATE server_claim_codes
SET consumed_at = COALESCE(consumed_at, created_at)
WHERE code_hash IN (SELECT code_hash FROM login_codes);

DROP TABLE IF EXISTS issued_login_code_hashes;

CREATE TABLE IF NOT EXISTS api_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  server_id TEXT REFERENCES servers(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  target TEXT,
  outcome TEXT NOT NULL,
  created_at INTEGER NOT NULL
) STRICT;
CREATE INDEX IF NOT EXISTS api_audit_server ON api_audit(server_id, id DESC);
CREATE TRIGGER IF NOT EXISTS api_audit_no_update
BEFORE UPDATE ON api_audit BEGIN
  SELECT RAISE(ABORT, 'api audit records are immutable');
END;
CREATE TRIGGER IF NOT EXISTS api_audit_no_delete
BEFORE DELETE ON api_audit BEGIN
  SELECT RAISE(ABORT, 'api audit records are immutable');
END;
`;

export class ApiDatabase {
  readonly db: DatabaseSync;

  constructor(path: string) {
    if (path !== ":memory:") mkdirSync(dirname(path), { recursive: true });
    this.db = new DatabaseSync(path);
    this.db.exec(
      "PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 5000; PRAGMA journal_mode = WAL;",
    );
    this.db.exec(MIGRATION);
    this.db
      .prepare("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(1, ?)")
      .run(now());
    this.db
      .prepare("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(2, ?)")
      .run(now());
    this.db
      .prepare("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(3, ?)")
      .run(now());
    this.db
      .prepare(
        "INSERT OR IGNORE INTO login_code_issuer_state(id, next_counter, key_material, exhausted, created_at) VALUES(1, ?, ?, 0, ?)",
      )
      .run(Buffer.alloc(10), randomBytes(32), now());
    this.deleteInactiveLoginCodes();
  }

  close(): void {
    this.db.close();
  }

  userCount(): number {
    return Number((this.db.prepare("SELECT COUNT(*) AS count FROM users").get() as Row).count);
  }

  createUser(
    username: string,
    passwordHash: string,
    systemRole: "owner" | "user" = "user",
  ): UserRecord {
    const id = randomUUID(),
      createdAt = now();
    this.db
      .prepare(
        "INSERT INTO users(id, username, system_role, password_hash, created_at) VALUES(?, ?, ?, ?, ?)",
      )
      .run(id, username, systemRole, passwordHash, createdAt);
    return { id, username, systemRole, passwordHash, createdAt, disabledAt: null };
  }

  findUserByUsername(username: string): UserRecord | null {
    const row = this.db
      .prepare("SELECT * FROM users WHERE username = ? COLLATE NOCASE")
      .get(username) as Row | undefined;
    return row ? mapUser(row) : null;
  }

  getUser(id: string): UserRecord | null {
    const row = this.db.prepare("SELECT * FROM users WHERE id = ?").get(id) as Row | undefined;
    return row ? mapUser(row) : null;
  }

  createSession(tokenHash: string, userId: string, csrfHash: string, expiresAt: number): void {
    this.db.prepare("DELETE FROM web_sessions WHERE expires_at <= ?").run(now());
    this.db
      .prepare(
        "INSERT INTO web_sessions(id, token_hash, user_id, csrf_hash, created_at, expires_at) VALUES(?, ?, ?, ?, ?, ?)",
      )
      .run(randomUUID(), tokenHash, userId, csrfHash, now(), expiresAt);
  }

  findSession(tokenHash: string): SessionRecord | null {
    const row = this.db
      .prepare(
        `
      SELECT s.id, s.user_id, u.username, u.system_role, s.csrf_hash, s.expires_at
      FROM web_sessions s JOIN users u ON u.id = s.user_id
      WHERE s.token_hash = ? AND s.expires_at > ? AND u.disabled_at IS NULL
    `,
      )
      .get(tokenHash, now()) as Row | undefined;
    return row
      ? {
          id: String(row.id),
          userId: String(row.user_id),
          username: String(row.username),
          systemRole: String(row.system_role) as "owner" | "user",
          csrfHash: String(row.csrf_hash),
          expiresAt: Number(row.expires_at),
        }
      : null;
  }

  deleteSession(tokenHash: string): void {
    this.db.prepare("DELETE FROM web_sessions WHERE token_hash = ?").run(tokenHash);
  }

  private nextLoginCode(): { code: string; codeHash: string } {
    const row = this.db
      .prepare(
        "SELECT next_counter, key_material, exhausted FROM login_code_issuer_state WHERE id = 1",
      )
      .get() as Row | undefined;
    if (!row) throw unavailable("LOGIN_CODE_STATE_MISSING", "Login code state is unavailable");
    if (Number(row.exhausted) === 1) {
      throw unavailable("LOGIN_CODE_SPACE_EXHAUSTED", "No more one-time codes are available");
    }
    if (!(row.next_counter instanceof Uint8Array) || !(row.key_material instanceof Uint8Array)) {
      throw unavailable("LOGIN_CODE_STATE_INVALID", "Login code state is invalid");
    }
    const normalized = loginCodeFromCounter(row.next_counter, row.key_material);
    const nextCounter = incrementLoginCodeCounter(row.next_counter);
    const updated = nextCounter
      ? this.db
          .prepare(
            "UPDATE login_code_issuer_state SET next_counter = ? WHERE id = 1 AND exhausted = 0",
          )
          .run(nextCounter)
      : this.db
          .prepare(
            "UPDATE login_code_issuer_state SET exhausted = 1 WHERE id = 1 AND exhausted = 0",
          )
          .run();
    if (updated.changes !== 1) {
      throw unavailable("LOGIN_CODE_STATE_CONFLICT", "Login code state could not be advanced");
    }
    return { code: normalized, codeHash: tokenDigest(normalized) };
  }

  private deleteInactiveLoginCodes(): void {
    const current = now();
    this.db
      .prepare(
        `UPDATE servers
         SET instance_id = 'released:' || id,
             token_hash = 'released:' || id,
             revoked_at = COALESCE(revoked_at, ?)
         WHERE revoked_at IS NOT NULL
           AND NOT EXISTS (
             SELECT 1 FROM server_memberships m WHERE m.server_id = servers.id
           )`,
      )
      .run(current);
    this.db
      .prepare(
        `DELETE FROM server_claim_codes
         WHERE server_id IN (
           SELECT id
           FROM servers
           WHERE revoked_at IS NOT NULL
             AND NOT EXISTS (
               SELECT 1 FROM server_memberships m WHERE m.server_id = servers.id
             )
         )`,
      )
      .run();
    this.db
      .prepare("DELETE FROM login_codes WHERE expires_at <= ? OR consumed_at IS NOT NULL")
      .run(current);
    this.db
      .prepare("DELETE FROM server_claim_codes WHERE expires_at <= ? OR consumed_at IS NOT NULL")
      .run(current);
  }

  createPairingCode(codeHash: string, createdBy: string, expiresAt: number): string {
    const id = randomUUID();
    this.db
      .prepare("DELETE FROM pairing_codes WHERE expires_at <= ? OR consumed_at IS NOT NULL")
      .run(now() - 86_400);
    this.db
      .prepare(
        "INSERT INTO pairing_codes(id, code_hash, created_by, created_at, expires_at) VALUES(?, ?, ?, ?, ?)",
      )
      .run(id, codeHash, createdBy, now(), expiresAt);
    return id;
  }

  createLoginOrClaimCode(
    serverId: string,
    expiresAt: number,
  ): { code: string; owner: Pick<UserRecord, "id" | "username"> | null } {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const owner = this.db
        .prepare(
          `SELECT u.* FROM users u JOIN server_memberships m ON m.user_id = u.id WHERE m.server_id = ? AND m.role = 'owner' AND u.disabled_at IS NULL`,
        )
        .get(serverId) as Row | undefined;
      const issued = this.nextLoginCode();
      if (owner) {
        const current = now();
        this.db
          .prepare(
            "DELETE FROM login_codes WHERE server_id = ? OR expires_at <= ? OR consumed_at IS NOT NULL",
          )
          .run(serverId, current);
        this.db
          .prepare(
            "INSERT INTO login_codes(id, code_hash, server_id, user_id, created_at, expires_at) VALUES(?, ?, ?, ?, ?, ?)",
          )
          .run(randomUUID(), issued.codeHash, serverId, String(owner.id), current, expiresAt);
      } else {
        this.insertServerClaimCode(serverId, issued.codeHash, expiresAt);
      }
      this.db.exec("COMMIT");
      return {
        code: issued.code,
        owner: owner ? { id: String(owner.id), username: String(owner.username) } : null,
      };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  private insertServerClaimCode(serverId: string, codeHash: string, expiresAt: number): void {
    const current = now();
    this.db
      .prepare(
        "DELETE FROM server_claim_codes WHERE server_id = ? OR expires_at <= ? OR consumed_at IS NOT NULL",
      )
      .run(serverId, current);
    this.db
      .prepare(
        "INSERT INTO server_claim_codes(id, code_hash, server_id, created_at, expires_at) VALUES(?, ?, ?, ?, ?)",
      )
      .run(randomUUID(), codeHash, serverId, current, expiresAt);
  }

  bootstrapServer(input: {
    instanceId: string;
    name: string;
    tokenHash: string;
    pluginVersion: string;
    protocolVersion: number;
    expiresAt: number;
  }): { server: ServerRecord; code: string } {
    this.deleteInactiveLoginCodes();
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const existing = this.db
        .prepare("SELECT * FROM servers WHERE instance_id = ?")
        .get(input.instanceId) as Row | undefined;
      if (existing && existing.revoked_at === null) {
        throw conflict(
          "SERVER_ALREADY_REGISTERED",
          "This server instance is already registered and must use its existing credential",
        );
      }
      const issued = this.nextLoginCode();
      const serverId = existing ? String(existing.id) : randomUUID();
      if (existing) {
        this.db.prepare("DELETE FROM login_codes WHERE server_id = ?").run(serverId);
        this.db.prepare("DELETE FROM server_claim_codes WHERE server_id = ?").run(serverId);
        this.db.prepare("DELETE FROM server_memberships WHERE server_id = ?").run(serverId);
        this.db
          .prepare(
            `UPDATE servers
             SET name = ?, token_hash = ?, plugin_version = ?, protocol_version = ?, last_seen_at = NULL, revoked_at = NULL
             WHERE id = ? AND revoked_at IS NOT NULL`,
          )
          .run(input.name, input.tokenHash, input.pluginVersion, input.protocolVersion, serverId);
      } else {
        this.db
          .prepare(
            `INSERT INTO servers(id, instance_id, name, token_hash, plugin_version, protocol_version, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)`,
          )
          .run(
            serverId,
            input.instanceId,
            input.name,
            input.tokenHash,
            input.pluginVersion,
            input.protocolVersion,
            now(),
          );
      }
      this.insertServerClaimCode(serverId, issued.codeHash, input.expiresAt);
      this.db.exec("COMMIT");
      return { server: this.getServer(serverId)!, code: issued.code };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  hasActiveServerClaimCode(codeHash: string): boolean {
    return Boolean(
      this.db
        .prepare(
          "SELECT 1 AS present FROM server_claim_codes WHERE code_hash = ? AND consumed_at IS NULL AND expires_at > ?",
        )
        .get(codeHash, now()),
    );
  }

  consumeServerClaimCode(
    codeHash: string,
    account: AccountTarget,
  ): { user: UserRecord; serverId: string } | null {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const current = now();
      const claim = this.db
        .prepare("SELECT * FROM server_claim_codes WHERE code_hash = ?")
        .get(codeHash) as Row | undefined;
      if (!claim || claim.consumed_at !== null || Number(claim.expires_at) <= current) {
        this.db.exec("COMMIT");
        return null;
      }
      const serverId = String(claim.server_id);
      const membership = this.db
        .prepare("SELECT 1 AS present FROM server_memberships WHERE server_id = ? LIMIT 1")
        .get(serverId) as Row | undefined;
      if (membership) {
        this.db.exec("COMMIT");
        return null;
      }
      let user: UserRecord;
      if ("userId" in account) {
        const row = this.db
          .prepare("SELECT * FROM users WHERE id = ? AND disabled_at IS NULL")
          .get(account.userId) as Row | undefined;
        if (!row) {
          this.db.exec("COMMIT");
          return null;
        }
        user = mapUser(row);
      } else {
        const userId = randomUUID();
        this.db
          .prepare(
            "INSERT INTO users(id, username, system_role, password_hash, created_at) VALUES(?, ?, 'user', ?, ?)",
          )
          .run(userId, account.username, account.passwordHash, current);
        user = {
          id: userId,
          username: account.username,
          systemRole: "user",
          passwordHash: account.passwordHash,
          createdAt: current,
          disabledAt: null,
        };
      }
      this.db
        .prepare(
          "INSERT INTO server_memberships(server_id, user_id, role, created_at) VALUES(?, ?, 'owner', ?)",
        )
        .run(serverId, user.id, current);
      const consumed = this.db
        .prepare(
          "UPDATE server_claim_codes SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL AND expires_at > ?",
        )
        .run(current, String(claim.id), current);
      if (consumed.changes !== 1) {
        this.db.exec("ROLLBACK");
        return null;
      }
      this.db.prepare("DELETE FROM server_claim_codes WHERE id = ?").run(String(claim.id));
      this.db.exec("COMMIT");
      return { user, serverId };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  findActiveLoginCode(codeHash: string): { user: UserRecord; serverId: string } | null {
    const row = this.db
      .prepare(
        `SELECT c.server_id, u.*
         FROM login_codes c
         JOIN users u ON u.id = c.user_id
         WHERE c.code_hash = ?
           AND c.consumed_at IS NULL
           AND c.expires_at > ?
           AND u.disabled_at IS NULL`,
      )
      .get(codeHash, now()) as Row | undefined;
    return row ? { user: mapUser(row), serverId: String(row.server_id) } : null;
  }

  isLegacyAccount(userId: string, serverId: string): boolean {
    return Boolean(
      this.db
        .prepare(
          `SELECT 1 AS present
           FROM users u
           WHERE u.id = ?
             AND u.username GLOB 'server-*'
             AND EXISTS (
               SELECT 1
               FROM api_audit a
               WHERE a.actor_user_id = u.id
                 AND a.server_id = ?
                 AND a.action = 'auth.code.claim'
             )`,
        )
        .get(userId, serverId),
    );
  }

  consumeLegacyLoginCode(
    codeHash: string,
    account: AccountTarget,
  ): { user: UserRecord; serverId: string } | null {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const current = now();
      const row = this.db
        .prepare(
          `SELECT c.id AS code_id, c.server_id, c.expires_at, c.consumed_at, u.*
           FROM login_codes c
           JOIN users u ON u.id = c.user_id
           WHERE c.code_hash = ? AND u.disabled_at IS NULL`,
        )
        .get(codeHash) as Row | undefined;
      if (
        !row ||
        row.consumed_at !== null ||
        Number(row.expires_at) <= current ||
        !this.isLegacyAccount(String(row.id), String(row.server_id))
      ) {
        this.db.exec("COMMIT");
        return null;
      }
      const legacyUserId = String(row.id);
      const serverId = String(row.server_id);
      let user: UserRecord;
      if ("userId" in account) {
        const target = this.db
          .prepare("SELECT * FROM users WHERE id = ? AND disabled_at IS NULL")
          .get(account.userId) as Row | undefined;
        if (!target || account.userId === legacyUserId) {
          this.db.exec("COMMIT");
          return null;
        }
        this.db
          .prepare("DELETE FROM server_memberships WHERE server_id = ? AND user_id = ?")
          .run(serverId, legacyUserId);
        this.db
          .prepare(
            `INSERT INTO server_memberships(server_id, user_id, role, created_at)
             VALUES(?, ?, 'owner', ?)
             ON CONFLICT(server_id, user_id) DO UPDATE SET role = 'owner'`,
          )
          .run(serverId, account.userId, current);
        user = mapUser(target);
      } else {
        const updated = this.db
          .prepare(
            "UPDATE users SET username = ?, password_hash = ? WHERE id = ? AND disabled_at IS NULL",
          )
          .run(account.username, account.passwordHash, legacyUserId);
        if (updated.changes !== 1) {
          this.db.exec("ROLLBACK");
          return null;
        }
        user = {
          ...mapUser(row),
          username: account.username,
          passwordHash: account.passwordHash,
        };
      }
      const consumed = this.db
        .prepare(
          "UPDATE login_codes SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL AND expires_at > ?",
        )
        .run(current, String(row.code_id), current);
      if (consumed.changes !== 1) {
        this.db.exec("ROLLBACK");
        return null;
      }
      this.db.prepare("DELETE FROM web_sessions WHERE user_id = ?").run(legacyUserId);
      this.db.prepare("DELETE FROM login_codes WHERE id = ?").run(String(row.code_id));
      this.db.exec("COMMIT");
      return { user, serverId };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  consumeLoginCode(codeHash: string): { user: UserRecord; serverId: string } | null {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const current = now();
      const row = this.db
        .prepare(
          `SELECT c.id AS code_id, c.server_id, c.expires_at, c.consumed_at, u.* FROM login_codes c JOIN users u ON u.id = c.user_id WHERE c.code_hash = ? AND u.disabled_at IS NULL`,
        )
        .get(codeHash) as Row | undefined;
      if (!row || row.consumed_at !== null || Number(row.expires_at) <= current) {
        this.db.exec("COMMIT");
        return null;
      }
      const consumed = this.db
        .prepare(
          "UPDATE login_codes SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL AND expires_at > ?",
        )
        .run(current, String(row.code_id), current);
      if (consumed.changes !== 1) {
        this.db.exec("COMMIT");
        return null;
      }
      this.db.prepare("DELETE FROM login_codes WHERE id = ?").run(String(row.code_id));
      this.db.exec("COMMIT");
      return { user: mapUser(row), serverId: String(row.server_id) };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  pairServer(input: {
    codeHash: string;
    instanceId: string;
    name: string;
    tokenHash: string;
    pluginVersion: string;
    protocolVersion: number;
  }): ServerRecord {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const pair = this.db
        .prepare("SELECT * FROM pairing_codes WHERE code_hash = ?")
        .get(input.codeHash) as Row | undefined;
      if (!pair || pair.consumed_at !== null || Number(pair.expires_at) <= now()) {
        throw notFound("Pairing code is invalid, expired, or already used");
      }
      const creator = String(pair.created_by);
      const existing = this.db
        .prepare("SELECT * FROM servers WHERE instance_id = ?")
        .get(input.instanceId) as Row | undefined;
      let serverId: string;
      if (existing) {
        serverId = String(existing.id);
        const membership = this.db
          .prepare("SELECT role FROM server_memberships WHERE server_id = ? AND user_id = ?")
          .get(serverId, creator) as Row | undefined;
        if (!membership || String(membership.role) !== "owner") {
          throw forbidden("Only an existing server owner may pair this instance again");
        }
        this.db
          .prepare(
            `UPDATE servers SET name = ?, token_hash = ?, plugin_version = ?, protocol_version = ?, revoked_at = NULL WHERE id = ?`,
          )
          .run(input.name, input.tokenHash, input.pluginVersion, input.protocolVersion, serverId);
      } else {
        serverId = randomUUID();
        this.db
          .prepare(
            `INSERT INTO servers(id, instance_id, name, token_hash, plugin_version, protocol_version, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)`,
          )
          .run(
            serverId,
            input.instanceId,
            input.name,
            input.tokenHash,
            input.pluginVersion,
            input.protocolVersion,
            now(),
          );
        this.db
          .prepare(
            "INSERT INTO server_memberships(server_id, user_id, role, created_at) VALUES(?, ?, 'owner', ?)",
          )
          .run(serverId, creator, now());
      }
      this.db
        .prepare("UPDATE pairing_codes SET consumed_at = ? WHERE id = ?")
        .run(now(), String(pair.id));
      this.db.exec("COMMIT");
      return this.getServer(serverId)!;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  getServer(id: string): ServerRecord | null {
    const row = this.db.prepare("SELECT * FROM servers WHERE id = ?").get(id) as Row | undefined;
    return row ? mapServer(row) : null;
  }

  getServerByToken(tokenHash: string): ServerRecord | null {
    const row = this.db
      .prepare("SELECT * FROM servers WHERE token_hash = ? AND revoked_at IS NULL")
      .get(tokenHash) as Row | undefined;
    return row ? mapServer(row) : null;
  }

  listServers(userId: string): ServerListRecord[] {
    return (
      this.db
        .prepare(
          `SELECT s.*, m.role FROM servers s JOIN server_memberships m ON m.server_id = s.id WHERE m.user_id = ? ORDER BY s.name COLLATE NOCASE, s.id`,
        )
        .all(userId) as Row[]
    ).map((row) => ({ ...mapServer(row), role: String(row.role) as ServerRole }));
  }

  listUsers(): Array<
    Pick<UserRecord, "id" | "username" | "systemRole" | "createdAt" | "disabledAt">
  > {
    return (
      this.db
        .prepare(
          "SELECT id, username, system_role, created_at, disabled_at FROM users ORDER BY username COLLATE NOCASE",
        )
        .all() as Row[]
    ).map((row) => ({
      id: String(row.id),
      username: String(row.username),
      systemRole: String(row.system_role) as "owner" | "user",
      createdAt: Number(row.created_at),
      disabledAt: nullableNumber(row.disabled_at),
    }));
  }

  listRecoverableLegacyServers(): LegacyServerRecord[] {
    return (
      this.db
        .prepare(
          `SELECT s.*, u.id AS legacy_user_id, u.username AS legacy_username
           FROM servers s
           JOIN server_memberships m ON m.server_id = s.id AND m.role = 'owner'
           JOIN users u ON u.id = m.user_id
           WHERE u.username GLOB 'server-*'
             AND EXISTS (
               SELECT 1
               FROM api_audit a
               WHERE a.actor_user_id = u.id
                 AND a.server_id = s.id
                 AND a.action = 'auth.code.claim'
             )
             AND NOT EXISTS (
               SELECT 1
               FROM server_memberships other
               WHERE other.server_id = s.id
                 AND other.role = 'owner'
                 AND other.user_id <> u.id
             )
           ORDER BY s.name COLLATE NOCASE, s.id`,
        )
        .all() as Row[]
    ).map((row) => ({
      ...mapServer(row),
      legacyUserId: String(row.legacy_user_id),
      legacyUsername: String(row.legacy_username),
    }));
  }

  recoverLegacyServer(serverId: string, targetUserId: string): LegacyServerRecord {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const row = this.db
        .prepare(
          `SELECT s.*, u.id AS legacy_user_id, u.username AS legacy_username
           FROM servers s
           JOIN server_memberships m ON m.server_id = s.id AND m.role = 'owner'
           JOIN users u ON u.id = m.user_id
           WHERE s.id = ?
             AND u.username GLOB 'server-*'
             AND EXISTS (
               SELECT 1
               FROM api_audit a
               WHERE a.actor_user_id = u.id
                 AND a.server_id = s.id
                 AND a.action = 'auth.code.claim'
             )
             AND NOT EXISTS (
               SELECT 1
               FROM server_memberships other
               WHERE other.server_id = s.id
                 AND other.role = 'owner'
                 AND other.user_id <> u.id
             )`,
        )
        .get(serverId) as Row | undefined;
      if (!row) throw notFound("Recoverable legacy server not found");
      const target = this.db
        .prepare("SELECT * FROM users WHERE id = ? AND disabled_at IS NULL")
        .get(targetUserId) as Row | undefined;
      if (!target || targetUserId === String(row.legacy_user_id)) {
        throw conflict("LEGACY_RECOVERY_TARGET_INVALID", "Choose a permanent active account");
      }
      const current = now();
      this.db
        .prepare("DELETE FROM server_memberships WHERE server_id = ? AND user_id = ?")
        .run(serverId, String(row.legacy_user_id));
      this.db
        .prepare(
          `INSERT INTO server_memberships(server_id, user_id, role, created_at)
           VALUES(?, ?, 'owner', ?)
           ON CONFLICT(server_id, user_id) DO UPDATE SET role = 'owner'`,
        )
        .run(serverId, targetUserId, current);
      this.db.prepare("DELETE FROM login_codes WHERE server_id = ?").run(serverId);
      this.db.prepare("DELETE FROM server_claim_codes WHERE server_id = ?").run(serverId);
      this.db.prepare("DELETE FROM web_sessions WHERE user_id = ?").run(String(row.legacy_user_id));
      this.db.exec("COMMIT");
      return {
        ...mapServer(row),
        legacyUserId: String(row.legacy_user_id),
        legacyUsername: String(row.legacy_username),
      };
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  listMemberships(serverId: string): Array<{ userId: string; username: string; role: ServerRole }> {
    return (
      this.db
        .prepare(
          `SELECT m.user_id, u.username, m.role FROM server_memberships m JOIN users u ON u.id = m.user_id WHERE m.server_id = ? ORDER BY u.username COLLATE NOCASE`,
        )
        .all(serverId) as Row[]
    ).map((row) => ({
      userId: String(row.user_id),
      username: String(row.username),
      role: String(row.role) as ServerRole,
    }));
  }

  setMembership(serverId: string, userId: string, role: Exclude<ServerRole, "owner">): void {
    if (!this.getUser(userId)) throw notFound("User not found");
    const existing = this.roleFor(serverId, userId);
    if (existing === "owner")
      throw conflict("OWNER_ROLE_IMMUTABLE", "The server owner role cannot be changed");
    this.db
      .prepare(
        `INSERT INTO server_memberships(server_id, user_id, role, created_at) VALUES(?, ?, ?, ?) ON CONFLICT(server_id, user_id) DO UPDATE SET role = excluded.role`,
      )
      .run(serverId, userId, role, now());
  }

  removeMembership(serverId: string, userId: string): void {
    const role = this.roleFor(serverId, userId);
    if (!role) throw notFound("Membership not found");
    if (role === "owner")
      throw conflict("OWNER_ROLE_IMMUTABLE", "The server owner cannot be removed");
    this.db
      .prepare("DELETE FROM server_memberships WHERE server_id = ? AND user_id = ?")
      .run(serverId, userId);
  }

  roleFor(serverId: string, userId: string): ServerRole | null {
    const row = this.db
      .prepare("SELECT role FROM server_memberships WHERE server_id = ? AND user_id = ?")
      .get(serverId, userId) as Row | undefined;
    return row ? (String(row.role) as ServerRole) : null;
  }

  requireRole(serverId: string, userId: string, allowed: readonly ServerRole[]): ServerRole {
    if (!this.getServer(serverId)) throw notFound("Server not found");
    const role = this.roleFor(serverId, userId);
    if (!role || !allowed.includes(role)) throw forbidden();
    return role;
  }

  touchServer(
    serverId: string,
    metadata?: { pluginVersion: string; protocolVersion: number },
  ): void {
    if (metadata) {
      this.db
        .prepare(
          "UPDATE servers SET last_seen_at = ?, plugin_version = ?, protocol_version = ? WHERE id = ?",
        )
        .run(now(), metadata.pluginVersion, metadata.protocolVersion, serverId);
    } else {
      this.db.prepare("UPDATE servers SET last_seen_at = ? WHERE id = ?").run(now(), serverId);
    }
  }

  revokeServer(serverId: string): void {
    const result = this.db
      .prepare("UPDATE servers SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL")
      .run(now(), serverId);
    if (result.changes === 0) throw conflict("SERVER_ALREADY_REVOKED", "Server is already revoked");
  }

  removeServer(serverId: string): void {
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const current = now();
      const releasedId = `removed:${serverId}`;
      const result = this.db
        .prepare("UPDATE servers SET instance_id = ?, token_hash = ?, revoked_at = ? WHERE id = ?")
        .run(releasedId, tokenDigest(releasedId), current, serverId);
      if (result.changes !== 1) throw notFound("Server not found");
      this.db.prepare("DELETE FROM login_codes WHERE server_id = ?").run(serverId);
      this.db.prepare("DELETE FROM server_claim_codes WHERE server_id = ?").run(serverId);
      this.db.prepare("DELETE FROM server_memberships WHERE server_id = ?").run(serverId);
      this.db.exec("COMMIT");
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }

  audit(
    actorUserId: string | null,
    serverId: string | null,
    action: string,
    target: string | null,
    outcome = "success",
  ): void {
    this.db
      .prepare(
        "INSERT INTO api_audit(actor_user_id, server_id, action, target, outcome, created_at) VALUES(?, ?, ?, ?, ?, ?)",
      )
      .run(actorUserId, serverId, action, target, outcome, now());
  }

  listAudit(userId: string, serverId: string | null, limit: number): AuditRecord[] {
    const rows = serverId
      ? this.db
          .prepare(
            `SELECT a.*, u.username AS actor_username FROM api_audit a LEFT JOIN users u ON u.id = a.actor_user_id JOIN server_memberships m ON m.server_id = a.server_id WHERE m.user_id = ? AND a.server_id = ? ORDER BY a.id DESC LIMIT ?`,
          )
          .all(userId, serverId, limit)
      : this.db
          .prepare(
            `SELECT a.*, u.username AS actor_username FROM api_audit a LEFT JOIN users u ON u.id = a.actor_user_id LEFT JOIN server_memberships m ON m.server_id = a.server_id AND m.user_id = ? WHERE (a.actor_user_id = ? OR m.user_id IS NOT NULL) ORDER BY a.id DESC LIMIT ?`,
          )
          .all(userId, userId, limit);
    return (rows as Row[]).map((row) => ({
      id: Number(row.id),
      actorUserId: nullableString(row.actor_user_id),
      actorUsername: nullableString(row.actor_username),
      serverId: nullableString(row.server_id),
      action: String(row.action),
      target: nullableString(row.target),
      outcome: String(row.outcome),
      createdAt: Number(row.created_at),
    }));
  }
}

function mapUser(row: Row): UserRecord {
  return {
    id: String(row.id),
    username: String(row.username),
    systemRole: String(row.system_role) as "owner" | "user",
    passwordHash: String(row.password_hash),
    createdAt: Number(row.created_at),
    disabledAt: nullableNumber(row.disabled_at),
  };
}

function mapServer(row: Row): ServerRecord {
  return {
    id: String(row.id),
    instanceId: String(row.instance_id),
    name: String(row.name),
    pluginVersion: String(row.plugin_version),
    protocolVersion: Number(row.protocol_version),
    createdAt: Number(row.created_at),
    lastSeenAt: nullableNumber(row.last_seen_at),
    revokedAt: nullableNumber(row.revoked_at),
  };
}

function nullableString(value: unknown): string | null {
  return value === null || value === undefined ? null : String(value);
}
function nullableNumber(value: unknown): number | null {
  return value === null || value === undefined ? null : Number(value);
}
function now(): number {
  return Math.floor(Date.now() / 1000);
}
