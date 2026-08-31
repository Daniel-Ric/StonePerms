import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";

import type { PluginBroker } from "./broker.js";
import type { ApiConfig } from "./config.js";
import type { ApiDatabase, SessionRecord } from "./database.js";
import { badRequest } from "./errors.js";

export const USERNAME_PATTERN = "^[A-Za-z0-9_.-]{3,32}$";
export const UUID_PATTERN =
  "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$";

export type RequestGuard = (request: FastifyRequest) => Promise<void>;

export interface ApiRouteContext {
  app: FastifyInstance;
  broker: PluginBroker;
  config: ApiConfig;
  database: ApiDatabase;
  requireAuth: RequestGuard;
  requireCsrf: RequestGuard;
  requireSystemOwner: RequestGuard;
  authenticatePlugin: RequestGuard;
  sessionCookie: string;
  csrfCookie: string;
}

export function setCookie(
  reply: FastifyReply,
  name: string,
  value: string,
  config: ApiConfig,
  httpOnly: boolean,
  expiresAt: number,
): void {
  reply.setCookie(name, value, {
    path: "/",
    httpOnly,
    secure: config.cookieSecure,
    sameSite: "strict",
    expires: new Date(expiresAt * 1000),
  });
}

export function normalizePairingCode(value: string): string {
  const result = value.replace(/[-\s]/g, "").toUpperCase();
  if (!/^[A-HJ-NP-Z2-9]{16}$/.test(result)) {
    throw badRequest("INVALID_PAIRING_CODE", "Pairing code has an invalid format");
  }
  return result;
}

export function normalizeLoginCode(value: string): string {
  const result = value.replace(/[-\s]/g, "").toUpperCase();
  if (!/^(?:[A-HJ-NP-Z2-9]{8}|[A-HJ-NP-Z2-9]{16})$/.test(result)) {
    throw badRequest("INVALID_LOGIN_CODE", "One-time code has an invalid format");
  }
  return result;
}

export function websocketUrl(publicUrl: string): string {
  const url = new URL("/v1/plugin/connect", publicUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function webActor(session: SessionRecord): string {
  return `web:${session.userId}:${session.username}`;
}

export function publicUser(user: {
  id: string;
  username: string;
  systemRole: "owner" | "user";
  createdAt: number;
  disabledAt: number | null;
}) {
  return {
    id: user.id,
    username: user.username,
    systemRole: user.systemRole,
    createdAt: user.createdAt,
    disabledAt: user.disabledAt,
  };
}

export function object(properties: Record<string, unknown>, required: readonly string[] = []) {
  return { type: "object", additionalProperties: false, properties, required };
}

export function secured(tags: string[]) {
  return { tags, security: [{ cookieSession: [] }] };
}

export function serverParams() {
  return object({ serverId: { type: "string", pattern: UUID_PATTERN } }, ["serverId"]);
}

export function serverResourceParams(resource: string, maxLength: number) {
  return object(
    { serverId: { type: "string", pattern: UUID_PATTERN }, [resource]: text(maxLength) },
    ["serverId", resource],
  );
}

export function text(maxLength: number) {
  return { type: "string", minLength: 1, maxLength };
}

export function integer() {
  return { type: "integer", minimum: -(2 ** 31), maximum: 2 ** 31 - 1 };
}

export function queryLimit() {
  return { type: "string", pattern: "^(?:[1-9]|[1-9][0-9]|1[0-9]{2}|200)$" };
}

export function parseQueryLimit(value: string | undefined): number {
  return value === undefined ? 50 : Number(value);
}
