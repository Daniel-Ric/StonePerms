import { resolve } from "node:path";

export interface ApiConfig {
  host: string;
  port: number;
  databasePath: string;
  publicUrl: string;
  allowedOrigins: ReadonlySet<string>;
  cookieSecure: boolean;
  trustProxy: boolean;
  sessionTtlSeconds: number;
  pairingTtlSeconds: number;
  loginCodeTtlSeconds: number;
  pluginRequestTimeoutMs: number;
  avatarProviderUrl: string | null;
  avatarRequestTimeoutMs: number;
  registrationEnabled: boolean;
  bootstrapUsername?: string;
  bootstrapPassword?: string;
  logger: boolean;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): ApiConfig {
  const host = text(env.STONEPERMS_HOST, "127.0.0.1");
  const port = integer(env.STONEPERMS_PORT, 3210, 1, 65_535, "STONEPERMS_PORT");
  const publicUrl = httpUrl(
    env.STONEPERMS_PUBLIC_URL ?? `http://${host}:${port}`,
    "STONEPERMS_PUBLIC_URL",
  );
  const cookieSecure = bool(env.STONEPERMS_COOKIE_SECURE, publicUrl.startsWith("https://"));
  if (cookieSecure && !publicUrl.startsWith("https://")) {
    throw new Error("STONEPERMS_COOKIE_SECURE=true requires an https public URL");
  }

  const bootstrapUsername = optionalText(env.STONEPERMS_BOOTSTRAP_USERNAME);
  const bootstrapPassword = optionalText(env.STONEPERMS_BOOTSTRAP_PASSWORD);
  if ((bootstrapUsername === undefined) !== (bootstrapPassword === undefined)) {
    throw new Error("Bootstrap username and password must either both be set or both be absent");
  }
  if (bootstrapPassword !== undefined && bootstrapPassword.length < 12) {
    throw new Error("STONEPERMS_BOOTSTRAP_PASSWORD must contain at least 12 characters");
  }
  const avatarProviderSetting = env.STONEPERMS_AVATAR_PROVIDER_URL;
  const avatarProviderUrl =
    avatarProviderSetting !== undefined &&
    ["", "off", "none", "disabled"].includes(avatarProviderSetting.trim().toLowerCase())
      ? null
      : providerUrl(avatarProviderSetting ?? "https://api.mcheads.org");

  return {
    host,
    port,
    databasePath: resolve(text(env.STONEPERMS_DATABASE, "./data/stoneperms-api.db")),
    publicUrl,
    allowedOrigins: new Set(
      text(env.STONEPERMS_ALLOWED_ORIGINS, publicUrl)
        .split(",")
        .map((value) => value.trim().replace(/\/$/, ""))
        .filter(Boolean),
    ),
    cookieSecure,
    trustProxy: bool(env.STONEPERMS_TRUST_PROXY, false),
    sessionTtlSeconds: integer(
      env.STONEPERMS_SESSION_TTL_SECONDS,
      43_200,
      900,
      604_800,
      "STONEPERMS_SESSION_TTL_SECONDS",
    ),
    pairingTtlSeconds: integer(
      env.STONEPERMS_PAIRING_TTL_SECONDS,
      600,
      60,
      3_600,
      "STONEPERMS_PAIRING_TTL_SECONDS",
    ),
    loginCodeTtlSeconds: integer(
      env.STONEPERMS_LOGIN_CODE_TTL_SECONDS,
      180,
      60,
      600,
      "STONEPERMS_LOGIN_CODE_TTL_SECONDS",
    ),
    pluginRequestTimeoutMs: integer(
      env.STONEPERMS_PLUGIN_REQUEST_TIMEOUT_MS,
      15_000,
      1_000,
      60_000,
      "STONEPERMS_PLUGIN_REQUEST_TIMEOUT_MS",
    ),
    avatarProviderUrl,
    avatarRequestTimeoutMs: integer(
      env.STONEPERMS_AVATAR_REQUEST_TIMEOUT_MS,
      5_000,
      500,
      15_000,
      "STONEPERMS_AVATAR_REQUEST_TIMEOUT_MS",
    ),
    registrationEnabled: bool(env.STONEPERMS_REGISTRATION_ENABLED, false),
    ...(bootstrapUsername === undefined ? {} : { bootstrapUsername }),
    ...(bootstrapPassword === undefined ? {} : { bootstrapPassword }),
    logger: bool(env.STONEPERMS_LOGGER, true),
  };
}

function text(value: string | undefined, fallback: string): string {
  const result = value?.trim() || fallback;
  if (result.includes("\0")) throw new Error("Configuration text contains a NUL byte");
  return result;
}

function optionalText(value: string | undefined): string | undefined {
  const result = value?.trim();
  return result ? result : undefined;
}

function integer(
  value: string | undefined,
  fallback: number,
  minimum: number,
  maximum: number,
  name: string,
): number {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
}

function bool(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) return fallback;
  if (["1", "true", "yes", "on"].includes(value.toLowerCase())) return true;
  if (["0", "false", "no", "off"].includes(value.toLowerCase())) return false;
  throw new Error(`Invalid boolean value ${JSON.stringify(value)}`);
}

function httpUrl(value: string, name: string): string {
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${name} must be an absolute HTTP(S) URL`);
  }
  if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new Error(`${name} must be an HTTP(S) URL without embedded credentials`);
  }
  parsed.pathname = parsed.pathname.replace(/\/$/, "");
  return parsed.toString().replace(/\/$/, "");
}

function providerUrl(value: string): string {
  const result = httpUrl(value, "STONEPERMS_AVATAR_PROVIDER_URL");
  const parsed = new URL(result);
  if (parsed.search || parsed.hash) {
    throw new Error("STONEPERMS_AVATAR_PROVIDER_URL must not contain a query or fragment");
  }
  return result;
}
