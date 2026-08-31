import { resolveAvatar } from "../avatar.js";
import type { ApiRouteContext } from "../http.js";
import { object, secured, serverParams, serverResourceParams, text, webActor } from "../http.js";

const ALL_SERVER_ROLES = ["owner", "admin", "editor", "viewer"] as const;

export function registerServerRoutes(context: ApiRouteContext): void {
  const { app, broker, config, database, requireAuth, requireCsrf } = context;

  app.get(
    "/v1/servers",
    { preHandler: requireAuth, schema: secured(["servers"]) },
    async (request) => ({
      servers: database
        .listServers(request.auth!.userId)
        .map((server) => ({ ...server, status: broker.status(server.id) })),
    }),
  );

  app.get(
    "/v1/servers/:serverId",
    { preHandler: requireAuth, schema: { ...secured(["servers"]), params: serverParams() } },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      const role = database.requireRole(serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      return {
        server: { ...database.getServer(serverId)!, role, status: broker.status(serverId) },
        memberships: database.listMemberships(serverId),
      };
    },
  );

  app.get(
    "/v1/servers/:serverId/directory",
    { preHandler: requireAuth, schema: { ...secured(["permissions"]), params: serverParams() } },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      return broker.request(serverId, "directory.snapshot", webActor(request.auth!), {});
    },
  );

  app.get(
    "/v1/servers/:serverId/display",
    { preHandler: requireAuth, schema: { ...secured(["display"]), params: serverParams() } },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      return broker.request(serverId, "display.getSettings", webActor(request.auth!), {});
    },
  );

  app.put(
    "/v1/servers/:serverId/display",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["display"]),
        params: serverParams(),
        body: object(
          {
            chatEnabled: { type: "boolean" },
            chatFormat: text(256),
            nametagEnabled: { type: "boolean" },
            nametagFormat: text(256),
          },
          ["chatEnabled", "chatFormat", "nametagEnabled", "nametagFormat"],
        ),
      },
    },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin"]);
      const result = await broker.request(
        serverId,
        "display.updateSettings",
        webActor(request.auth!),
        request.body,
      );
      database.audit(request.auth!.userId, serverId, "display.settings.update", null);
      return result;
    },
  );

  app.get(
    "/v1/servers/:serverId/settings",
    { preHandler: requireAuth, schema: { ...secured(["settings"]), params: serverParams() } },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      return broker.request(serverId, "settings.get", webActor(request.auth!), {});
    },
  );

  app.put(
    "/v1/servers/:serverId/settings",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["settings"]),
        params: serverParams(),
        body: object(
          {
            defaultGroup: text(64),
            serverContext: text(64),
            includeDeviceOsContext: { type: "boolean" },
            includeLocaleContext: { type: "boolean" },
            expiryCheckSeconds: { type: "integer", minimum: 1, maximum: 60 },
            catalogRefreshSeconds: { type: "integer", minimum: 1, maximum: 300 },
            debug: { type: "boolean" },
          },
          [
            "defaultGroup",
            "serverContext",
            "includeDeviceOsContext",
            "includeLocaleContext",
            "expiryCheckSeconds",
            "catalogRefreshSeconds",
            "debug",
          ],
        ),
      },
    },
    async (request) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin"]);
      const result = await broker.request(
        serverId,
        "settings.update",
        webActor(request.auth!),
        request.body,
      );
      database.audit(request.auth!.userId, serverId, "plugin.settings.update", null);
      return result;
    },
  );

  app.get(
    "/v1/servers/:serverId/players/:identifier",
    {
      preHandler: requireAuth,
      schema: { ...secured(["players"]), params: serverResourceParams("identifier", 128) },
    },
    async (request) => {
      const { serverId, identifier } = request.params as { serverId: string; identifier: string };
      database.requireRole(serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      return broker.request(serverId, "player.inspect", webActor(request.auth!), { identifier });
    },
  );

  app.get(
    "/v1/servers/:serverId/players/:identifier/avatar",
    {
      preHandler: requireAuth,
      schema: { ...secured(["players"]), params: serverResourceParams("identifier", 128) },
    },
    async (request, reply) => {
      const { serverId, identifier } = request.params as { serverId: string; identifier: string };
      database.requireRole(serverId, request.auth!.userId, [...ALL_SERVER_ROLES]);
      const payload = await broker.request(serverId, "player.avatar", webActor(request.auth!), {
        identifier,
      });
      const avatar = await resolveAvatar(payload, config);
      if (avatar === null) {
        reply.header("Cache-Control", "private, max-age=60");
        return reply.status(204).send();
      }
      reply.header("Cache-Control", "private, max-age=300, stale-while-revalidate=3600");
      reply.header("ETag", avatar.etag);
      reply.header("X-StonePerms-Avatar-Source", avatar.source);
      if (request.headers["if-none-match"] === avatar.etag) return reply.status(304).send();
      return reply.type("image/png").send(avatar.bytes);
    },
  );
}
