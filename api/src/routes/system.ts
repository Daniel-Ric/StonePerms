import type { ApiRouteContext } from "../http.js";
import { object } from "../http.js";

export function registerSystemRoutes({ app, config, database }: ApiRouteContext): void {
  app.get(
    "/health",
    { schema: { tags: ["system"], response: { 200: object({ status: { type: "string" } }) } } },
    async () => ({ status: "ok" }),
  );

  app.get("/ready", { schema: { tags: ["system"] } }, async () => {
    database.db.prepare("SELECT 1").get();
    return { status: "ready" };
  });

  app.get("/v1/public-config", { schema: { tags: ["system"] } }, async () => ({
    registrationEnabled: config.registrationEnabled,
  }));
}
