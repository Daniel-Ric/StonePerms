import { randomUUID } from "node:crypto";
import type WebSocket from "ws";

import type { ApiDatabase, ServerRecord } from "./database.js";
import { ApiError, unavailable } from "./errors.js";

interface PendingRequest {
  timer: NodeJS.Timeout;
  resolve: (payload: unknown) => void;
  reject: (error: Error) => void;
}

export interface PluginCommand {
  type: "request";
  requestId: string;
  action: PluginAction;
  actor: string;
  payload: unknown;
}

interface Connection {
  socket: WebSocket;
  server: ServerRecord;
  ready: boolean;
  connectedAt: number;
  pending: Map<string, PendingRequest>;
}

interface PollingConnection {
  server: ServerRecord;
  connectedAt: number;
  lastSeenAt: number;
  lastDatabaseTouchAt: number;
  queue: PluginCommand[];
  pending: Map<string, PendingRequest>;
}

export interface PluginStatus {
  online: boolean;
  ready: boolean;
  connectedAt: number | null;
}

export type PluginAction =
  | "editor.createSession"
  | "editor.applyChanges"
  | "directory.snapshot"
  | "display.getSettings"
  | "display.updateSettings"
  | "settings.get"
  | "settings.update"
  | "player.inspect"
  | "player.avatar"
  | "group.create"
  | "group.setWeight"
  | "group.delete"
  | "track.create"
  | "track.rename"
  | "track.clone"
  | "track.delete"
  | "track.moveUser"
  | "audit.list";

export class PluginBroker {
  private readonly connections = new Map<string, Connection>();
  private readonly pollingConnections = new Map<string, PollingConnection>();

  constructor(
    private readonly database: ApiDatabase,
    private readonly requestTimeoutMs: number,
  ) {}

  attach(socket: WebSocket, server: ServerRecord): void {
    const old = this.connections.get(server.id);
    if (old) old.socket.close(4001, "Replaced by a newer connection");

    const connection: Connection = {
      socket,
      server,
      ready: false,
      connectedAt: Date.now(),
      pending: new Map(),
    };
    this.connections.set(server.id, connection);

    socket.on("message", (data, binary) => {
      const bytes = Array.isArray(data) ? Buffer.concat(data) : Buffer.from(data as ArrayBuffer);
      if (binary || bytes.length > 1_048_576) {
        socket.close(1009, "Text messages up to 1 MiB are required");
        return;
      }
      this.onMessage(connection, bytes.toString("utf8"));
    });
    socket.on("close", () =>
      this.detach(connection, unavailable("PLUGIN_OFFLINE", "Plugin disconnected")),
    );
    socket.on("error", () =>
      this.detach(connection, unavailable("PLUGIN_OFFLINE", "Plugin connection failed")),
    );

    const helloTimer = setTimeout(() => {
      if (!connection.ready) socket.close(4002, "Hello timeout");
    }, 5_000);
    helloTimer.unref();
    socket.once("close", () => clearTimeout(helloTimer));
  }

  status(serverId: string): PluginStatus {
    const connection = this.connections.get(serverId);
    if (connection?.ready && connection.socket.readyState === connection.socket.OPEN) {
      return {
        online: true,
        ready: true,
        connectedAt: Math.floor(connection.connectedAt / 1000),
      };
    }
    const polling = this.activePollingConnection(serverId);
    if (polling) {
      return {
        online: true,
        ready: true,
        connectedAt: Math.floor(polling.connectedAt / 1000),
      };
    }
    if (connection) {
      return {
        online: true,
        ready: false,
        connectedAt: Math.floor(connection.connectedAt / 1000),
      };
    }
    return { online: false, ready: false, connectedAt: null };
  }

  async request(
    serverId: string,
    action: PluginAction,
    actor: string,
    payload: unknown,
  ): Promise<unknown> {
    const connection = this.connections.get(serverId);
    if (connection?.ready && connection.socket.readyState === connection.socket.OPEN) {
      return this.requestOverWebSocket(connection, action, actor, payload);
    }
    const polling = this.activePollingConnection(serverId);
    if (polling) return this.requestOverHttp(polling, action, actor, payload);
    throw unavailable("PLUGIN_OFFLINE", "The StonePerms plugin is not connected");
  }

  poll(server: ServerRecord): PluginCommand | null {
    const now = Date.now();
    let connection = this.pollingConnections.get(server.id);
    if (!connection) {
      connection = {
        server,
        connectedAt: now,
        lastSeenAt: now,
        lastDatabaseTouchAt: 0,
        queue: [],
        pending: new Map(),
      };
      this.pollingConnections.set(server.id, connection);
    } else {
      connection.server = server;
      connection.lastSeenAt = now;
    }
    if (now - connection.lastDatabaseTouchAt >= 20_000) {
      this.database.touchServer(server.id);
      connection.lastDatabaseTouchAt = now;
    }
    return connection.queue.shift() ?? null;
  }

  acceptHttpResponse(serverId: string, message: Record<string, unknown>): void {
    if (typeof message.requestId !== "string" || typeof message.ok !== "boolean") {
      throw new ApiError(400, "INVALID_PLUGIN_RESPONSE", "Plugin response is invalid");
    }
    const connection = this.pollingConnections.get(serverId);
    const pending = connection?.pending.get(message.requestId);
    if (!connection || !pending) return;
    connection.pending.delete(message.requestId);
    clearTimeout(pending.timer);
    if (message.ok && exactKeys(message, ["requestId", "ok", "payload"])) {
      pending.resolve(message.payload);
      return;
    }
    if (
      !message.ok &&
      exactKeys(message, ["requestId", "ok", "error"]) &&
      message.error &&
      typeof message.error === "object" &&
      !Array.isArray(message.error)
    ) {
      const error = message.error as Record<string, unknown>;
      const code = typeof error.code === "string" ? error.code.slice(0, 64) : "PLUGIN_REJECTED";
      const description =
        typeof error.message === "string"
          ? error.message.slice(0, 500)
          : "Plugin rejected the request";
      pending.reject(new ApiError(422, code, description));
      return;
    }
    pending.reject(
      new ApiError(502, "INVALID_PLUGIN_RESPONSE", "Plugin returned an invalid response"),
    );
  }

  private requestOverWebSocket(
    connection: Connection,
    action: PluginAction,
    actor: string,
    payload: unknown,
  ): Promise<unknown> {
    const requestId = randomUUID();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        connection.pending.delete(requestId);
        reject(unavailable("PLUGIN_TIMEOUT", "The StonePerms plugin did not answer in time"));
      }, this.requestTimeoutMs);
      timer.unref();
      connection.pending.set(requestId, { timer, resolve, reject });
      connection.socket.send(
        JSON.stringify({ type: "request", requestId, action, actor, payload }),
        (error) => {
          if (error) {
            clearTimeout(timer);
            connection.pending.delete(requestId);
            reject(unavailable("PLUGIN_OFFLINE", "Could not send the request to the plugin"));
          }
        },
      );
    });
  }

  private requestOverHttp(
    connection: PollingConnection,
    action: PluginAction,
    actor: string,
    payload: unknown,
  ): Promise<unknown> {
    const requestId = randomUUID();
    const command: PluginCommand = { type: "request", requestId, action, actor, payload };
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        connection.pending.delete(requestId);
        connection.queue = connection.queue.filter((item) => item.requestId !== requestId);
        reject(unavailable("PLUGIN_TIMEOUT", "The StonePerms plugin did not answer in time"));
      }, this.requestTimeoutMs);
      timer.unref();
      connection.pending.set(requestId, { timer, resolve, reject });
      connection.queue.push(command);
    });
  }

  disconnect(serverId: string): void {
    this.connections.get(serverId)?.socket.close(4003, "Server credential revoked");
    const polling = this.pollingConnections.get(serverId);
    if (polling) {
      this.rejectPollingConnection(
        polling,
        unavailable("PLUGIN_OFFLINE", "Server credential revoked"),
      );
      this.pollingConnections.delete(serverId);
    }
  }

  close(): void {
    for (const connection of this.connections.values())
      connection.socket.close(1001, "API shutting down");
    this.connections.clear();
    for (const connection of this.pollingConnections.values()) {
      this.rejectPollingConnection(
        connection,
        unavailable("PLUGIN_OFFLINE", "API is shutting down"),
      );
    }
    this.pollingConnections.clear();
  }

  private activePollingConnection(serverId: string): PollingConnection | null {
    const connection = this.pollingConnections.get(serverId);
    if (!connection) return null;
    if (Date.now() - connection.lastSeenAt <= 5_000) return connection;
    this.rejectPollingConnection(
      connection,
      unavailable("PLUGIN_OFFLINE", "Plugin connection expired"),
    );
    this.pollingConnections.delete(serverId);
    return null;
  }

  private rejectPollingConnection(connection: PollingConnection, error: Error): void {
    for (const pending of connection.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    connection.pending.clear();
    connection.queue = [];
  }

  private onMessage(connection: Connection, raw: string): void {
    let message: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
      message = parsed as Record<string, unknown>;
    } catch {
      connection.socket.close(1007, "Invalid JSON object");
      return;
    }

    if (message.type === "hello") {
      if (
        connection.ready ||
        !exactKeys(message, ["type", "instanceId", "pluginVersion", "protocolVersion"]) ||
        message.instanceId !== connection.server.instanceId ||
        typeof message.pluginVersion !== "string" ||
        message.pluginVersion.length > 64 ||
        message.protocolVersion !== 1
      ) {
        connection.socket.close(4004, "Invalid or unsupported hello");
        return;
      }
      connection.ready = true;
      this.database.touchServer(connection.server.id, {
        pluginVersion: message.pluginVersion,
        protocolVersion: message.protocolVersion,
      });
      connection.socket.send(
        JSON.stringify({ type: "helloAck", protocolVersion: 1, heartbeatSeconds: 20 }),
      );
      return;
    }

    if (!connection.ready) {
      connection.socket.close(4005, "Hello required first");
      return;
    }
    if (message.type === "heartbeat" && exactKeys(message, ["type"])) {
      this.database.touchServer(connection.server.id);
      connection.socket.send(JSON.stringify({ type: "heartbeatAck" }));
      return;
    }
    if (message.type === "response") {
      this.onResponse(connection, message);
      return;
    }
    connection.socket.close(1008, "Unsupported message");
  }

  private onResponse(connection: Connection, message: Record<string, unknown>): void {
    if (typeof message.requestId !== "string" || typeof message.ok !== "boolean") {
      connection.socket.close(1008, "Invalid response");
      return;
    }
    const pending = connection.pending.get(message.requestId);
    if (!pending) return;
    connection.pending.delete(message.requestId);
    clearTimeout(pending.timer);
    if (message.ok && exactKeys(message, ["type", "requestId", "ok", "payload"])) {
      pending.resolve(message.payload);
      return;
    }
    if (
      !message.ok &&
      exactKeys(message, ["type", "requestId", "ok", "error"]) &&
      message.error &&
      typeof message.error === "object" &&
      !Array.isArray(message.error)
    ) {
      const error = message.error as Record<string, unknown>;
      const code = typeof error.code === "string" ? error.code.slice(0, 64) : "PLUGIN_REJECTED";
      const description =
        typeof error.message === "string"
          ? error.message.slice(0, 500)
          : "Plugin rejected the request";
      pending.reject(new ApiError(422, code, description));
      return;
    }
    pending.reject(
      new ApiError(502, "INVALID_PLUGIN_RESPONSE", "Plugin returned an invalid response"),
    );
  }

  private detach(connection: Connection, error: Error): void {
    if (this.connections.get(connection.server.id) !== connection) return;
    this.connections.delete(connection.server.id);
    for (const pending of connection.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    connection.pending.clear();
  }
}

function exactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}
