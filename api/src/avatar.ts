import { createHash } from "node:crypto";

import { PNG } from "pngjs";

import type { ApiConfig } from "./config.js";

const MAX_AVATAR_BYTES = 512 * 1024;
const MAX_METADATA_BYTES = 64 * 1024;
const FACE_SIZE = 128;
const PNG_SIGNATURE = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
const GEYSER_API_URL = "https://api.geysermc.org";
const MINECRAFT_TEXTURE_URL = "https://textures.minecraft.net/texture";

export interface AvatarImage {
  bytes: Buffer;
  etag: string;
  source: "geyser" | "mcheads" | "local";
}

interface PluginAvatar {
  name: string | null;
  xuid: string | null;
  skinId: string | null;
  mimeType: string | null;
  data: string | null;
}

export async function resolveAvatar(
  payload: unknown,
  config: ApiConfig,
): Promise<AvatarImage | null> {
  const avatar = parsePluginAvatar(payload);
  const local =
    avatar.mimeType === "image/png" && avatar.data !== null ? decodeBase64(avatar.data) : null;
  const persona = avatar.skinId?.toLowerCase().startsWith("persona-") ?? false;
  if (!persona && local !== null) return image(local, "local");

  if (config.avatarProviderUrl !== null) {
    const capturedXuid =
      avatar.xuid !== null && /^\d{1,20}$/.test(avatar.xuid) ? avatar.xuid : null;
    const geyserXuid =
      capturedXuid ??
      (persona && avatar.name !== null
        ? await fetchGeyserXuid(avatar.name, config.avatarRequestTimeoutMs)
        : null);
    if (geyserXuid !== null) {
      const converted = await fetchGeyserAvatar(geyserXuid, config.avatarRequestTimeoutMs);
      if (converted !== null) return image(converted, "geyser");
    }

    const identifiers = [
      avatar.xuid !== null && /^\d{1,20}$/.test(avatar.xuid) ? avatar.xuid : null,
      avatar.name !== null ? `.${avatar.name}` : null,
    ].filter((value): value is string => value !== null);
    for (const identifier of new Set(identifiers)) {
      const external = await fetchExternalAvatar(
        config.avatarProviderUrl,
        identifier,
        config.avatarRequestTimeoutMs,
      );
      if (external !== null) return image(external, "mcheads");
    }
  }
  return null;
}

async function fetchGeyserXuid(gamertag: string, timeoutMs: number): Promise<string | null> {
  try {
    const response = await fetch(`${GEYSER_API_URL}/v2/xbox/xuid/${encodeURIComponent(gamertag)}`, {
      headers: { Accept: "application/json", "User-Agent": "StonePerms-API/0.8" },
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const metadata = await readJsonObject(response);
    const xuid = metadata?.xuid;
    if (typeof xuid === "number" && Number.isSafeInteger(xuid) && xuid > 0) return String(xuid);
    return typeof xuid === "string" && /^\d{1,20}$/.test(xuid) ? xuid : null;
  } catch {
    return null;
  }
}

async function fetchGeyserAvatar(xuid: string, timeoutMs: number): Promise<Buffer | null> {
  try {
    const metadataResponse = await fetch(`${GEYSER_API_URL}/v2/skin/${xuid}`, {
      headers: { Accept: "application/json", "User-Agent": "StonePerms-API/0.8" },
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const metadata = await readJsonObject(metadataResponse);
    const textureId = metadata?.texture_id;
    if (typeof textureId !== "string" || !/^[a-f0-9]{64}$/i.test(textureId)) return null;

    const textureResponse = await fetch(`${MINECRAFT_TEXTURE_URL}/${textureId.toLowerCase()}`, {
      headers: { Accept: "image/png", "User-Agent": "StonePerms-API/0.8" },
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (
      !textureResponse.ok ||
      !(textureResponse.headers.get("content-type") ?? "").toLowerCase().startsWith("image/png")
    ) {
      return null;
    }
    const declaredTextureLength = Number(textureResponse.headers.get("content-length") ?? 0);
    if (declaredTextureLength > MAX_AVATAR_BYTES) return null;
    const texture = Buffer.from(await textureResponse.arrayBuffer());
    return renderFacePng(texture);
  } catch {
    return null;
  }
}

async function readJsonObject(response: Response): Promise<Record<string, unknown> | null> {
  if (!response.ok) return null;
  const declaredLength = Number(response.headers.get("content-length") ?? 0);
  if (declaredLength > MAX_METADATA_BYTES) return null;
  const text = await response.text();
  if (Buffer.byteLength(text, "utf8") > MAX_METADATA_BYTES) return null;
  const value = JSON.parse(text) as unknown;
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

async function fetchExternalAvatar(
  providerUrl: string,
  player: string,
  timeoutMs: number,
): Promise<Buffer | null> {
  try {
    const response = await fetch(`${providerUrl}/head/${encodeURIComponent(player)}/128`, {
      headers: { Accept: "image/png", "User-Agent": "StonePerms-API/0.8" },
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (
      !response.ok ||
      !(response.headers.get("content-type") ?? "").toLowerCase().startsWith("image/")
    ) {
      return null;
    }
    const declaredLength = Number(response.headers.get("content-length") ?? 0);
    if (declaredLength > MAX_AVATAR_BYTES) return null;
    const bytes = Buffer.from(await response.arrayBuffer());
    return validPng(bytes) ? bytes : null;
  } catch {
    return null;
  }
}

function parsePluginAvatar(payload: unknown): PluginAvatar {
  if (payload === null || typeof payload !== "object" || Array.isArray(payload)) {
    return { name: null, xuid: null, skinId: null, mimeType: null, data: null };
  }
  const value = payload as Record<string, unknown>;
  return {
    name:
      typeof value.name === "string" && value.name.length <= 64 && value.name.trim() !== ""
        ? value.name.trim()
        : null,
    xuid: typeof value.xuid === "string" && value.xuid.length <= 20 ? value.xuid : null,
    skinId: typeof value.skinId === "string" && value.skinId.length <= 128 ? value.skinId : null,
    mimeType: typeof value.mimeType === "string" ? value.mimeType : null,
    data: typeof value.data === "string" ? value.data : null,
  };
}

function decodeBase64(value: string): Buffer | null {
  if (value.length > Math.ceil(MAX_AVATAR_BYTES / 3) * 4 || !/^[A-Za-z0-9+/]*={0,2}$/.test(value)) {
    return null;
  }
  const bytes = Buffer.from(value, "base64");
  return validPng(bytes) ? bytes : null;
}

function validPng(bytes: Buffer): boolean {
  return (
    bytes.length >= PNG_SIGNATURE.length &&
    bytes.length <= MAX_AVATAR_BYTES &&
    bytes.subarray(0, 8).equals(PNG_SIGNATURE)
  );
}

function renderFacePng(bytes: Buffer): Buffer | null {
  if (!validPng(bytes) || bytes.length < 24) return null;
  const declaredWidth = bytes.readUInt32BE(16);
  const declaredHeight = bytes.readUInt32BE(20);
  if (
    declaredWidth < 64 ||
    declaredWidth > 256 ||
    declaredWidth % 64 !== 0 ||
    declaredHeight < declaredWidth / 2 ||
    declaredHeight > 256
  )
    return null;

  try {
    const skin = PNG.sync.read(bytes);
    if (skin.width !== declaredWidth || skin.height !== declaredHeight) return null;
    const scale = skin.width / 64;
    const sourceSize = 8 * scale;
    if (skin.width < 48 * scale || skin.height < 16 * scale) return null;

    const face = new PNG({ width: FACE_SIZE, height: FACE_SIZE });
    for (let y = 0; y < FACE_SIZE; y += 1) {
      const sourceY = Math.floor((y * sourceSize) / FACE_SIZE);
      for (let x = 0; x < FACE_SIZE; x += 1) {
        const sourceX = Math.floor((x * sourceSize) / FACE_SIZE);
        const base = pixel(skin, 8 * scale + sourceX, 8 * scale + sourceY);
        const overlay = pixel(skin, 40 * scale + sourceX, 8 * scale + sourceY);
        const composed = alphaOver(base, overlay);
        const target = (y * FACE_SIZE + x) * 4;
        face.data[target] = composed[0];
        face.data[target + 1] = composed[1];
        face.data[target + 2] = composed[2];
        face.data[target + 3] = composed[3];
      }
    }
    return PNG.sync.write(face, { colorType: 6 });
  } catch {
    return null;
  }
}

function pixel(imageData: PNG, x: number, y: number): [number, number, number, number] {
  const offset = (y * imageData.width + x) * 4;
  return [
    imageData.data[offset] ?? 0,
    imageData.data[offset + 1] ?? 0,
    imageData.data[offset + 2] ?? 0,
    imageData.data[offset + 3] ?? 0,
  ];
}

function alphaOver(
  base: [number, number, number, number],
  overlay: [number, number, number, number],
): [number, number, number, number] {
  const baseAlpha = base[3];
  const overlayAlpha = overlay[3];
  const outputAlpha = overlayAlpha + Math.floor((baseAlpha * (255 - overlayAlpha) + 127) / 255);
  if (outputAlpha === 0) return [0, 0, 0, 0];
  const channel = (baseChannel: number, overlayChannel: number): number => {
    const numerator =
      overlayChannel * overlayAlpha * 255 + baseChannel * baseAlpha * (255 - overlayAlpha);
    return Math.floor((numerator + outputAlpha * 127) / (outputAlpha * 255));
  };
  return [
    channel(base[0], overlay[0]),
    channel(base[1], overlay[1]),
    channel(base[2], overlay[2]),
    outputAlpha,
  ];
}

function image(bytes: Buffer, source: AvatarImage["source"]): AvatarImage {
  return {
    bytes,
    etag: `"${createHash("sha256").update(bytes).digest("base64url")}"`,
    source,
  };
}
