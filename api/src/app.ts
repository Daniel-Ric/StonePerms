import cookie from "@fastify/cookie";
import cors from "@fastify/cors";
import helmet from "@fastify/helmet";
import rateLimit from "@fastify/rate-limit";
import fastifyStatic from "@fastify/static";
import swagger from "@fastify/swagger";
import swaggerUi from "@fastify/swagger-ui";
import websocket from "@fastify/websocket";
import Fastify, { type FastifyInstance, type FastifyRequest } from "fastify";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { PluginBroker } from "./broker.js";
import type { ApiConfig } from "./config.js";
import { constantEqual, hashPassword, tokenDigest } from "./crypto.js";
import { ApiDatabase, type ServerRecord, type SessionRecord } from "./database.js";
import { ApiError, forbidden, unauthorized } from "./errors.js";
import type { ApiRouteContext } from "./http.js";
import { USERNAME_PATTERN } from "./http.js";
import { registerAccessAndEditorRoutes } from "./routes/access.js";
import { registerAuthRoutes } from "./routes/auth.js";
import { registerGroupAndTrackRoutes } from "./routes/groups.js";
import { registerPairingRoutes } from "./routes/pairing.js";
import { registerServerRoutes } from "./routes/servers.js";
import { registerSystemRoutes } from "./routes/system.js";

declare module "fastify" {
  interface FastifyRequest {
    auth?: SessionRecord;
    pluginServer?: ServerRecord;
  }
}

export interface StonePermsApi {
  app: FastifyInstance;
  database: ApiDatabase;
  broker: PluginBroker;
}

const moduleDirectory = dirname(fileURLToPath(import.meta.url));
const productionDashboardRoot = resolve(moduleDirectory, "../../../dashboard/dist");
const developmentDashboardRoot = resolve(moduleDirectory, "../../dashboard/dist");
const dashboardRoot = existsSync(productionDashboardRoot)
  ? productionDashboardRoot
  : developmentDashboardRoot;

export async function buildApp(config: ApiConfig): Promise<StonePermsApi> {
  const database = new ApiDatabase(config.databasePath);
  try {
    await bootstrap(database, config);
  } catch (error) {
    database.close();
    throw error;
  }

  const broker = new PluginBroker(database, config.pluginRequestTimeoutMs);
  const app = Fastify({
    logger: config.logger,
    trustProxy: config.trustProxy,
    bodyLimit: 1_048_576,
    requestTimeout: 20_000,
    ajv: { customOptions: { allErrors: false, coerceTypes: false, removeAdditional: false } },
  });
  const sessionCookie = config.cookieSecure ? "__Host-stoneperms-session" : "stoneperms-session";
  const csrfCookie = config.cookieSecure ? "__Host-stoneperms-csrf" : "stoneperms-csrf";

  await app.register(websocket, { options: { maxPayload: 1_048_576 } });
  await app.register(cookie);
  await app.register(cors, {
    credentials: true,
    origin(origin, callback) {
      if (!origin || config.allowedOrigins.has(origin.replace(/\/$/, ""))) {
        callback(null, true);
      } else {
        callback(new Error("Origin is not allowed"), false);
      }
    },
  });
  await app.register(helmet, {
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        baseUri: ["'self'"],
        connectSrc: ["'self'"],
        fontSrc: ["'self'", "data:"],
        formAction: ["'self'"],
        frameAncestors: ["'none'"],
        imgSrc: ["'self'", "data:"],
        objectSrc: ["'none'"],
        scriptSrc: ["'self'"],
        styleSrc: ["'self'", "'unsafe-inline'"],
      },
    },
  });
  await app.register(rateLimit, { max: 300, timeWindow: "1 minute" });
  await app.register(swagger, {
    openapi: {
      info: {
        title: "StonePerms API",
        version: "0.8.12",
        description: "API and live bridge for the StonePerms dashboard and Endstone plugin",
      },
      components: {
        securitySchemes: { cookieSession: { type: "apiKey", in: "cookie", name: sessionCookie } },
      },
    },
  });
  await app.register(swaggerUi, { routePrefix: "/docs" });
  if (existsSync(dashboardRoot)) {
    await app.register(fastifyStatic, { root: dashboardRoot, wildcard: true });
  }

  app.addHook("onClose", async () => {
    broker.close();
    database.close();
  });
  app.addHook("onSend", async (request, reply, payload) => {
    if (!reply.hasHeader("Cache-Control")) {
      reply.header(
        "Cache-Control",
        request.url.startsWith("/assets/") ? "public, max-age=31536000, immutable" : "no-store",
      );
    }
    return payload;
  });

  app.setErrorHandler((error, request, reply) => {
    if (error instanceof ApiError) {
      void reply
        .status(error.statusCode)
        .send({ error: { code: error.code, message: error.message } });
      return;
    }
    const generic = error as { validation?: unknown; message?: string };
    if (generic.validation) {
      void reply.status(400).send({
        error: { code: "INVALID_REQUEST", message: "Request does not match the API schema" },
      });
      return;
    }
    if (generic.message === "Origin is not allowed") {
      void reply
        .status(403)
        .send({ error: { code: "ORIGIN_FORBIDDEN", message: "Origin is not allowed" } });
      return;
    }
    request.log.error({ err: error }, "Unhandled API error");
    void reply
      .status(500)
      .send({ error: { code: "INTERNAL_ERROR", message: "Internal server error" } });
  });

  const requireAuth = async (request: FastifyRequest): Promise<void> => {
    const token = request.cookies[sessionCookie];
    if (!token) throw unauthorized();
    const session = database.findSession(tokenDigest(token));
    if (!session) throw unauthorized("Session is invalid or expired");
    request.auth = session;
  };
  const requireCsrf = async (request: FastifyRequest): Promise<void> => {
    await requireAuth(request);
    const cookieValue = request.cookies[csrfCookie];
    const headerValue = request.headers["x-csrf-token"];
    if (
      !cookieValue ||
      typeof headerValue !== "string" ||
      !constantEqual(tokenDigest(cookieValue), request.auth!.csrfHash) ||
      !constantEqual(cookieValue, headerValue)
    ) {
      throw forbidden("CSRF token is missing or invalid");
    }
  };
  const requireSystemOwner = async (request: FastifyRequest): Promise<void> => {
    await requireCsrf(request);
    if (request.auth!.systemRole !== "owner") {
      throw forbidden("System owner permission required");
    }
  };
  const authenticatePlugin = async (request: FastifyRequest): Promise<void> => {
    const authorization = request.headers.authorization;
    if (!authorization?.startsWith("Bearer ")) {
      throw unauthorized("Plugin bearer token required");
    }
    const token = authorization.slice(7);
    if (!token.startsWith("sp_srv_") || token.length > 128) {
      throw unauthorized("Invalid plugin credential");
    }
    const server = database.getServerByToken(tokenDigest(token));
    if (!server) throw unauthorized("Plugin credential is invalid or revoked");
    request.pluginServer = server;
  };

  const routes: ApiRouteContext = {
    app,
    broker,
    config,
    database,
    requireAuth,
    requireCsrf,
    requireSystemOwner,
    authenticatePlugin,
    sessionCookie,
    csrfCookie,
  };
  registerSystemRoutes(routes);
  await registerAuthRoutes(routes);
  registerPairingRoutes(routes);
  registerServerRoutes(routes);
  registerGroupAndTrackRoutes(routes);
  registerAccessAndEditorRoutes(routes);

  if (existsSync(dashboardRoot)) {
    app.setNotFoundHandler(async (request, reply) => {
      if (
        request.method === "GET" &&
        !request.url.startsWith("/v1/") &&
        !request.url.startsWith("/docs")
      ) {
        return reply.type("text/html").sendFile("index.html");
      }
      return reply.status(404).send({
        error: { code: "NOT_FOUND", message: "Resource not found" },
      });
    });
  }

  await app.ready();
  return { app, database, broker };
}

async function bootstrap(database: ApiDatabase, config: ApiConfig): Promise<void> {
  if (database.userCount() > 0) return;
  if (!config.bootstrapUsername || !config.bootstrapPassword) {
    throw new Error(
      "Database has no users. Set STONEPERMS_BOOTSTRAP_USERNAME and STONEPERMS_BOOTSTRAP_PASSWORD for the first start.",
    );
  }
  if (!new RegExp(USERNAME_PATTERN).test(config.bootstrapUsername)) {
    throw new Error("Bootstrap username is invalid");
  }
  database.createUser(
    config.bootstrapUsername,
    await hashPassword(config.bootstrapPassword),
    "owner",
  );
}
