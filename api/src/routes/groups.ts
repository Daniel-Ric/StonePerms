import type { ApiRouteContext } from "../http.js";
import {
  integer,
  object,
  secured,
  serverParams,
  serverResourceParams,
  text,
  UUID_PATTERN,
  webActor,
} from "../http.js";

export function registerGroupAndTrackRoutes(context: ApiRouteContext): void {
  const { app, broker, database, requireCsrf } = context;

  app.post(
    "/v1/servers/:serverId/groups",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["groups"]),
        params: serverParams(),
        body: object(
          {
            name: text(64),
            displayName: { anyOf: [text(128), { type: "null" }] },
            weight: integer(),
          },
          ["name", "displayName", "weight"],
        ),
      },
    },
    async (request, reply) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin"]);
      const result = await broker.request(
        serverId,
        "group.create",
        webActor(request.auth!),
        request.body,
      );
      database.audit(
        request.auth!.userId,
        serverId,
        "group.create",
        (request.body as { name: string }).name,
      );
      return reply.status(201).send(result);
    },
  );

  app.patch(
    "/v1/servers/:serverId/groups/:name",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["groups"]),
        params: serverResourceParams("name", 64),
        body: object({ weight: integer() }, ["weight"]),
      },
    },
    async (request) => {
      const { serverId, name } = request.params as { serverId: string; name: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin"]);
      const body = request.body as { weight: number };
      const result = await broker.request(serverId, "group.setWeight", webActor(request.auth!), {
        name,
        weight: body.weight,
      });
      database.audit(request.auth!.userId, serverId, "group.weight.set", `${name}:${body.weight}`);
      return result;
    },
  );

  app.delete(
    "/v1/servers/:serverId/groups/:name",
    {
      preHandler: requireCsrf,
      schema: { ...secured(["groups"]), params: serverResourceParams("name", 64) },
    },
    async (request, reply) => {
      const { serverId, name } = request.params as { serverId: string; name: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin"]);
      await broker.request(serverId, "group.delete", webActor(request.auth!), { name });
      database.audit(request.auth!.userId, serverId, "group.delete", name);
      return reply.status(204).send();
    },
  );

  app.post(
    "/v1/servers/:serverId/tracks",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["tracks"]),
        params: serverParams(),
        body: object({ name: text(64) }, ["name"]),
      },
    },
    async (request, reply) => {
      const { serverId } = request.params as { serverId: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin", "editor"]);
      const result = await broker.request(
        serverId,
        "track.create",
        webActor(request.auth!),
        request.body,
      );
      database.audit(
        request.auth!.userId,
        serverId,
        "track.create",
        (request.body as { name: string }).name,
      );
      return reply.status(201).send(result);
    },
  );

  app.post(
    "/v1/servers/:serverId/tracks/:name/rename",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["tracks"]),
        params: serverResourceParams("name", 64),
        body: object({ newName: text(64) }, ["newName"]),
      },
    },
    async (request) => {
      const { serverId, name } = request.params as { serverId: string; name: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin", "editor"]);
      const newName = (request.body as { newName: string }).newName;
      const result = await broker.request(serverId, "track.rename", webActor(request.auth!), {
        name,
        newName,
      });
      database.audit(request.auth!.userId, serverId, "track.rename", `${name}:${newName}`);
      return result;
    },
  );

  app.post(
    "/v1/servers/:serverId/tracks/:name/clone",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["tracks"]),
        params: serverResourceParams("name", 64),
        body: object({ cloneName: text(64) }, ["cloneName"]),
      },
    },
    async (request, reply) => {
      const { serverId, name } = request.params as { serverId: string; name: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin", "editor"]);
      const cloneName = (request.body as { cloneName: string }).cloneName;
      const result = await broker.request(serverId, "track.clone", webActor(request.auth!), {
        name,
        cloneName,
      });
      database.audit(request.auth!.userId, serverId, "track.clone", `${name}:${cloneName}`);
      return reply.status(201).send(result);
    },
  );

  app.delete(
    "/v1/servers/:serverId/tracks/:name",
    {
      preHandler: requireCsrf,
      schema: { ...secured(["tracks"]), params: serverResourceParams("name", 64) },
    },
    async (request, reply) => {
      const { serverId, name } = request.params as { serverId: string; name: string };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin", "editor"]);
      await broker.request(serverId, "track.delete", webActor(request.auth!), { name });
      database.audit(request.auth!.userId, serverId, "track.delete", name);
      return reply.status(204).send();
    },
  );

  app.post(
    "/v1/servers/:serverId/players/:identifier/tracks/:track/:direction",
    {
      preHandler: requireCsrf,
      schema: {
        ...secured(["players", "tracks"]),
        params: object(
          {
            serverId: { type: "string", pattern: UUID_PATTERN },
            identifier: text(128),
            track: text(64),
            direction: { type: "string", enum: ["promote", "demote"] },
          },
          ["serverId", "identifier", "track", "direction"],
        ),
      },
    },
    async (request) => {
      const { serverId, identifier, track, direction } = request.params as {
        serverId: string;
        identifier: string;
        track: string;
        direction: "promote" | "demote";
      };
      database.requireRole(serverId, request.auth!.userId, ["owner", "admin", "editor"]);
      const result = await broker.request(serverId, "track.moveUser", webActor(request.auth!), {
        identifier,
        track,
        direction,
      });
      database.audit(
        request.auth!.userId,
        serverId,
        `track.${direction}`,
        `${identifier}:${track}`,
      );
      return result;
    },
  );
}
