import type WebSocket from "ws";

import { randomPairingCode, randomToken, tokenDigest } from "../crypto.js";
import type { ApiRouteContext } from "../http.js";
import { normalizePairingCode, object, secured, UUID_PATTERN, websocketUrl } from "../http.js";

export function registerPairingRoutes(context: ApiRouteContext): void {
  const { app, authenticatePlugin, broker, config, database, requireCsrf } = context;

  app.post(
    "/v1/pairing-codes",
    { preHandler: requireCsrf, schema: secured(["pairing"]) },
    async (request, reply) => {
      const code = randomPairingCode();
      const expiresAt = Math.floor(Date.now() / 1000) + config.pairingTtlSeconds;
      database.createPairingCode(
        tokenDigest(normalizePairingCode(code)),
        request.auth!.userId,
        expiresAt,
      );
      database.audit(request.auth!.userId, null, "pairing.create", null);
      return reply.status(201).send({ code, expiresAt });
    },
  );

  app.post(
    "/v1/plugin/bootstrap-login-codes",
    {
      config: { rateLimit: { max: 5, timeWindow: "15 minutes" } },
      schema: {
        tags: ["plugin", "auth"],
        body: object(
          {
            instanceId: { type: "string", pattern: UUID_PATTERN },
            name: { type: "string", minLength: 1, maxLength: 80 },
            pluginVersion: { type: "string", minLength: 1, maxLength: 64 },
            protocolVersion: { type: "integer", minimum: 1, maximum: 1 },
          },
          ["instanceId", "name", "pluginVersion", "protocolVersion"],
        ),
      },
    },
    async (request, reply) => {
      const body = request.body as {
        instanceId: string;
        name: string;
        pluginVersion: string;
        protocolVersion: number;
      };
      const expiresAt = Math.floor(Date.now() / 1000) + config.loginCodeTtlSeconds;
      const serverToken = randomToken("sp_srv_");
      const { server, code } = database.bootstrapServer({
        ...body,
        tokenHash: tokenDigest(serverToken),
        expiresAt,
      });
      database.audit(null, server.id, "auth.code.bootstrap", body.instanceId);
      return reply.status(201).send({
        code,
        expiresAt,
        serverId: server.id,
        serverToken,
        dashboardUrl: new URL("/login?method=code", config.publicUrl).toString(),
      });
    },
  );

  app.post(
    "/v1/plugin/pair",
    {
      config: { rateLimit: { max: 10, timeWindow: "1 minute" } },
      schema: {
        tags: ["plugin"],
        body: object(
          {
            code: { type: "string", minLength: 16, maxLength: 32 },
            instanceId: { type: "string", pattern: UUID_PATTERN },
            name: { type: "string", minLength: 1, maxLength: 80 },
            pluginVersion: { type: "string", minLength: 1, maxLength: 64 },
            protocolVersion: { type: "integer", minimum: 1, maximum: 1 },
          },
          ["code", "instanceId", "name", "pluginVersion", "protocolVersion"],
        ),
      },
    },
    async (request, reply) => {
      const body = request.body as {
        code: string;
        instanceId: string;
        name: string;
        pluginVersion: string;
        protocolVersion: number;
      };
      const serverToken = randomToken("sp_srv_");
      const server = database.pairServer({
        ...body,
        codeHash: tokenDigest(normalizePairingCode(body.code)),
        tokenHash: tokenDigest(serverToken),
      });
      database.audit(null, server.id, "plugin.pair", body.instanceId);
      return reply.status(201).send({
        serverId: server.id,
        serverToken,
        websocketUrl: websocketUrl(config.publicUrl),
        protocolVersion: 1,
      });
    },
  );

  app.delete(
    "/v1/plugin/credential",
    { preHandler: authenticatePlugin, schema: { tags: ["plugin"] } },
    async (request, reply) => {
      const serverId = request.pluginServer!.id;
      database.revokeServer(serverId);
      database.audit(null, serverId, "plugin.unpair", null);
      broker.disconnect(serverId);
      return reply.status(204).send();
    },
  );

  app.post(
    "/v1/plugin/login-codes",
    {
      preHandler: authenticatePlugin,
      config: { rateLimit: { max: 5, timeWindow: "1 minute" } },
      schema: { tags: ["plugin", "auth"] },
    },
    async (request, reply) => {
      const expiresAt = Math.floor(Date.now() / 1000) + config.loginCodeTtlSeconds;
      const serverId = request.pluginServer!.id;
      const { code, owner } = database.createLoginOrClaimCode(serverId, expiresAt);
      database.audit(null, serverId, "auth.code.create", owner?.id ?? "server-claim");
      return reply.status(201).send({
        code,
        expiresAt,
        ...(owner ? { username: owner.username } : {}),
        dashboardUrl: new URL("/login?method=code", config.publicUrl).toString(),
      });
    },
  );

  app.post(
    "/v1/plugin/poll",
    {
      preHandler: authenticatePlugin,
      config: { rateLimit: { max: 6_000, timeWindow: "1 minute" } },
      schema: { tags: ["plugin"], body: object({}) },
    },
    async (request) => ({
      request: broker.poll(request.pluginServer!),
      pollAfterMs: 750,
    }),
  );

  app.post(
    "/v1/plugin/responses",
    {
      preHandler: authenticatePlugin,
      config: { rateLimit: { max: 6_000, timeWindow: "1 minute" } },
      schema: {
        tags: ["plugin"],
        body: object(
          {
            requestId: { type: "string", pattern: UUID_PATTERN },
            ok: { type: "boolean" },
            payload: {},
            error: object(
              {
                code: { type: "string", minLength: 1, maxLength: 64 },
                message: { type: "string", minLength: 1, maxLength: 500 },
              },
              ["code", "message"],
            ),
          },
          ["requestId", "ok"],
        ),
      },
    },
    async (request, reply) => {
      broker.acceptHttpResponse(request.pluginServer!.id, request.body as Record<string, unknown>);
      return reply.status(204).send();
    },
  );

  app.get(
    "/v1/plugin/connect",
    { websocket: true, preValidation: authenticatePlugin },
    (socket: WebSocket, request) => {
      broker.attach(socket, request.pluginServer!);
    },
  );
}
