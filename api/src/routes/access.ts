import type { ApiRouteContext } from "../http.js";
import { notFound } from "../errors.js";
import {
  object,
  parseQueryLimit,
  queryLimit,
  secured,
  serverParams,
  UUID_PATTERN,
  USERNAME_PATTERN,
  webActor,
} from "../http.js";

const ALL_SERVER_ROLES = ["owner", "admin", "editor", "viewer"] as const;

export function registerAccessAndEditorRoutes(context: ApiRouteContext): void {
  const { app, broker, database, requireAuth, requireCsrf } = context;

  app.get(
    "/v1/servers/:serverId/plugin-audit",
    {
      preHandler: requireAuth,
      schema: {
        ...secured(["audit"]),
        params: serverParams(),
        querystring: object({ limit: queryLimit() }, []),
      },
    },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      const limit = parseQueryLimit((request.query as { limit?: string }).limit);
      return broker.request(serverId, "audit.list", webActor(request.auth!), { limit });
    },
  );

  app.put(
    "/v1/servers/:serverId/memberships/:userId",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["servers"]),
        params: membershipParams(),
        body: object({ role: { type: "string", enum: ["admin", "editor", "viewer"] } }, ["role"]),
      },
    },
    async (request) => {
      const { serverId, userId } = request.params as { serverId: string; userId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner"]);
      const role = (request.body as { role: "admin" | "editor" | "viewer" }).role;
      database.setMembership(serverId, userId, role);
      database.audit(request.auth!.userId, serverId, "membership.set", `${userId}:${role}`);
      return { userId, role };
    },
  );

  app.post(
    "/v1/servers/:serverId/memberships",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["servers"]),
        params: serverParams(),
        body: object(
          {
            username: { type: "string", pattern: USERNAME_PATTERN },
            role: { type: "string", enum: ["admin", "editor", "viewer"] },
          },
          ["username", "role"],
        ),
      },
    },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner"]);
      const body = request.body as {
        username: string;
        role: "admin" | "editor" | "viewer";
      };
      const user = database.findUserByUsername(body.username);
      if (!user || user.disabledAt !== null) throw notFound("Web user not found");
      database.setMembership(serverId, user.id, body.role);
      database.audit(request.auth!.userId, serverId, "membership.set", `${user.id}:${body.role}`);
      return { userId: user.id, username: user.username, role: body.role };
    },
  );

  app.delete(
    "/v1/servers/:serverId/memberships/:userId",
    {
      preHandler: requireCsrf,
      schema: { ...secured(["servers"]), params: membershipParams() },
    },
    async (request, reply) => {
      const { serverId, userId } = request.params as { serverId: string; userId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner"]);
      database.removeMembership(serverId, userId);
      database.audit(request.auth!.userId, serverId, "membership.remove", userId);
      return reply.status(204).send();
    },
  );

  app.delete(
    "/v1/servers/:serverId/credential",
    { preHandler: requireCsrf, schema: { ...secured(["servers"]), params: serverParams() } },
    async (request, reply) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner"]);
      database.revokeServer(serverId);
      broker.disconnect(serverId);
      database.audit(request.auth!.userId, serverId, "server.revoke", null);
      return reply.status(204).send();
    },
  );

  app.post(
    "/v1/servers/:serverId/editor/sessions",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["editor"]),
        params: serverParams(),
        body: object(
          {
            users: {
              type: "array",
              maxItems: 500,
              uniqueItems: true,
              items: { type: "string", minLength: 1, maxLength: 128 },
            },
            includeGroups: { type: "boolean" },
            includeTracks: { type: "boolean" },
          },
          ["users", "includeGroups", "includeTracks"],
        ),
      },
    },
    async (request, reply) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      const actor = webActor(request.auth!);
      try {
        const result = await broker.request(serverId, "editor.createSession", actor, request.body);
        database.audit(request.auth!.userId, serverId, "editor.session.create", null);
        return reply.status(201).send(result);
      } catch (error) {
        database.audit(request.auth!.userId, serverId, "editor.session.create", null, "failed");
        throw error;
      }
    },
  );

  app.post(
    "/v1/servers/:serverId/editor/changes",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["editor"]),
        params: serverParams(),
        body: { type: "object", additionalProperties: true, maxProperties: 20 },
      },
    },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin", "editor"]);
      const actor = webActor(request.auth!);
      try {
        const result = await broker.request(serverId, "editor.applyChanges", actor, request.body);
        database.audit(request.auth!.userId, serverId, "editor.changes.apply", null);
        return result;
      } catch (error) {
        database.audit(request.auth!.userId, serverId, "editor.changes.apply", null, "failed");
        throw error;
      }
    },
  );

  app.get(
    "/v1/audit",
    {
      preHandler: requireAuth,
      schema: {
        ...secured(["audit"]),
        querystring: object(
          { serverId: { type: "string", pattern: UUID_PATTERN }, limit: queryLimit() },
          [],
        ),
      },
    },
    async (request) => {
      const query = request.query as { serverId?: string; limit?: string };
      if (query.serverId) {
        database.requireRole(query.serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      }
      return {
        entries: database.listAudit(
          request.auth!.userId,
          query.serverId ?? null,
          parseQueryLimit(query.limit),
        ),
      };
    },
  );
}

function membershipParams() {
  return object(
    {
      serverId: { type: "string", pattern: UUID_PATTERN },
      userId: { type: "string", pattern: UUID_PATTERN },
    },
    ["serverId", "userId"],
  );
}
