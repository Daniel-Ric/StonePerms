import { hashPassword, randomToken, tokenDigest, verifyPassword } from "../crypto.js";
import { conflict, forbidden, unauthorized } from "../errors.js";
import type { ApiRouteContext } from "../http.js";
import {
  normalizeLoginCode,
  object,
  publicUser,
  secured,
  setCookie,
  USERNAME_PATTERN,
} from "../http.js";

export async function registerAuthRoutes(context: ApiRouteContext): Promise<void> {
  const {
    app,
    config,
    csrfCookie,
    database,
    requireAuth,
    requireCsrf,
    requireSystemOwner,
    sessionCookie,
  } = context;
  const dummyPasswordHash = await hashPassword(randomToken("dummy_"));

  app.get("/v1/session", { schema: { tags: ["auth"] } }, async (request, reply) => {
    const token = request.cookies[sessionCookie];
    if (!token) return { user: null };

    const session = database.findSession(tokenDigest(token));
    if (!session) {
      reply.clearCookie(sessionCookie, { path: "/" }).clearCookie(csrfCookie, { path: "/" });
      return { user: null };
    }
    return {
      user: {
        id: session.userId,
        username: session.username,
        systemRole: session.systemRole,
      },
    };
  });

  app.post(
    "/v1/auth/login",
    {
      config: { rateLimit: { max: 10, timeWindow: "1 minute" } },
      schema: {
        tags: ["auth"],
        body: object(
          {
            username: { type: "string", pattern: USERNAME_PATTERN },
            password: { type: "string", minLength: 1, maxLength: 1024 },
          },
          ["username", "password"],
        ),
      },
    },
    async (request, reply) => {
      const body = request.body as { username: string; password: string };
      const user = database.findUserByUsername(body.username);
      const passwordMatches = await verifyPassword(
        body.password,
        user?.passwordHash ?? dummyPasswordHash,
      );
      if (!user || user.disabledAt !== null || !passwordMatches) {
        throw unauthorized("Username or password is incorrect");
      }

      const sessionToken = randomToken("sp_web_");
      const csrfToken = randomToken("sp_csrf_");
      const expiresAt = Math.floor(Date.now() / 1000) + config.sessionTtlSeconds;
      database.createSession(tokenDigest(sessionToken), user.id, tokenDigest(csrfToken), expiresAt);
      setCookie(reply, sessionCookie, sessionToken, config, true, expiresAt);
      setCookie(reply, csrfCookie, csrfToken, config, false, expiresAt);
      database.audit(user.id, null, "auth.login", null);
      return { user: publicUser(user), csrfToken, expiresAt };
    },
  );

  app.post(
    "/v1/auth/register",
    {
      config: { rateLimit: { max: 5, timeWindow: "15 minutes" } },
      schema: {
        tags: ["auth"],
        body: object(
          {
            username: { type: "string", pattern: USERNAME_PATTERN },
            password: { type: "string", minLength: 12, maxLength: 1024 },
          },
          ["username", "password"],
        ),
      },
    },
    async (request, reply) => {
      if (!config.registrationEnabled) {
        throw forbidden("Account registration is not available on this StonePerms instance");
      }
      const body = request.body as { username: string; password: string };
      if (database.findUserByUsername(body.username)) {
        throw conflict("USERNAME_EXISTS", "Username already exists");
      }

      const user = database.createUser(body.username, await hashPassword(body.password));
      const sessionToken = randomToken("sp_web_");
      const csrfToken = randomToken("sp_csrf_");
      const expiresAt = Math.floor(Date.now() / 1000) + config.sessionTtlSeconds;
      database.createSession(tokenDigest(sessionToken), user.id, tokenDigest(csrfToken), expiresAt);
      setCookie(reply, sessionCookie, sessionToken, config, true, expiresAt);
      setCookie(reply, csrfCookie, csrfToken, config, false, expiresAt);
      database.audit(user.id, null, "auth.register", user.id);
      return reply.status(201).send({ user: publicUser(user), csrfToken, expiresAt });
    },
  );

  app.post(
    "/v1/auth/code",
    {
      config: { rateLimit: { max: 10, timeWindow: "1 minute" } },
      schema: {
        tags: ["auth"],
        body: object({ code: { type: "string", minLength: 8, maxLength: 19 } }, ["code"]),
      },
    },
    async (request, reply) => {
      const body = request.body as { code: string };
      const codeHash = tokenDigest(normalizeLoginCode(body.code));
      let result = database.consumeLoginCode(codeHash);
      let claimedServer = false;
      if (!result && database.hasActiveServerClaimCode(codeHash)) {
        const username = `server-${randomToken("", 6)}`;
        const passwordHash = await hashPassword(randomToken("sp_password_"));
        result = database.consumeServerClaimCode(codeHash, username, passwordHash);
        claimedServer = result !== null;
      }
      if (!result) {
        throw unauthorized("One-time code is invalid, expired, or already used");
      }

      const sessionToken = randomToken("sp_web_");
      const csrfToken = randomToken("sp_csrf_");
      const expiresAt = Math.floor(Date.now() / 1000) + config.sessionTtlSeconds;
      database.createSession(
        tokenDigest(sessionToken),
        result.user.id,
        tokenDigest(csrfToken),
        expiresAt,
      );
      setCookie(reply, sessionCookie, sessionToken, config, true, expiresAt);
      setCookie(reply, csrfCookie, csrfToken, config, false, expiresAt);
      database.audit(
        result.user.id,
        result.serverId,
        claimedServer ? "auth.code.claim" : "auth.code.login",
        null,
      );
      return { user: publicUser(result.user), csrfToken, expiresAt, claimedServer };
    },
  );

  app.post(
    "/v1/auth/logout",
    { preHandler: requireCsrf, schema: secured(["auth"]) },
    async (request, reply) => {
      const token = request.cookies[sessionCookie]!;
      database.deleteSession(tokenDigest(token));
      database.audit(request.auth!.userId, null, "auth.logout", null);
      reply.clearCookie(sessionCookie, { path: "/" }).clearCookie(csrfCookie, { path: "/" });
      return reply.status(204).send();
    },
  );

  app.get("/v1/me", { preHandler: requireAuth, schema: secured(["auth"]) }, async (request) => ({
    user: {
      id: request.auth!.userId,
      username: request.auth!.username,
      systemRole: request.auth!.systemRole,
    },
  }));

  app.get("/v1/users", { preHandler: requireAuth, schema: secured(["users"]) }, async (request) => {
    if (request.auth!.systemRole !== "owner") {
      throw forbidden("System owner permission required");
    }
    return { users: database.listUsers() };
  });

  app.post(
    "/v1/users",
    {
      preHandler: requireSystemOwner,
      schema: {
        ...secured(["users"]),
        body: object(
          {
            username: { type: "string", pattern: USERNAME_PATTERN },
            password: { type: "string", minLength: 12, maxLength: 1024 },
          },
          ["username", "password"],
        ),
      },
    },
    async (request, reply) => {
      const body = request.body as { username: string; password: string };
      if (database.findUserByUsername(body.username)) {
        throw conflict("USERNAME_EXISTS", "Username already exists");
      }
      const user = database.createUser(body.username, await hashPassword(body.password));
      database.audit(request.auth!.userId, null, "user.create", user.id);
      return reply.status(201).send({ user: publicUser(user) });
    },
  );
}
