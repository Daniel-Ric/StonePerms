import {
  createHash,
  createHmac,
  randomBytes,
  scrypt as scryptCallback,
  timingSafeEqual,
} from "node:crypto";
const PASSWORD_N = 32_768;
const PASSWORD_R = 8;
const PASSWORD_P = 1;
const PASSWORD_KEY_LENGTH = 64;
const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const LOGIN_CODE_COUNTER_BYTES = 10;
const LOGIN_CODE_HALF_BYTES = 5;
const LOGIN_CODE_ROUNDS = 6;
const LOGIN_CODE_DOMAIN = Buffer.from("stoneperms/login-code/v1", "utf8");

export function randomToken(prefix: string, bytes = 32): string {
  return `${prefix}${randomBytes(bytes).toString("base64url")}`;
}

export function tokenDigest(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

export function randomPairingCode(): string {
  const bytes = randomBytes(16);
  const characters = Array.from(bytes, (value) => CODE_ALPHABET[value % CODE_ALPHABET.length]).join(
    "",
  );
  return `${characters.slice(0, 4)}-${characters.slice(4, 8)}-${characters.slice(8, 12)}-${characters.slice(12)}`;
}

export function loginCodeFromCounter(counter: Uint8Array, key: Uint8Array): string {
  if (counter.byteLength !== LOGIN_CODE_COUNTER_BYTES) {
    throw new Error("Login code counter must contain 10 bytes");
  }
  if (key.byteLength !== 32) throw new Error("Login code key must contain 32 bytes");

  let left = Buffer.from(counter.slice(0, LOGIN_CODE_HALF_BYTES));
  let right = Buffer.from(counter.slice(LOGIN_CODE_HALF_BYTES));
  for (let round = 0; round < LOGIN_CODE_ROUNDS; round += 1) {
    const mask = createHmac("sha256", key)
      .update(LOGIN_CODE_DOMAIN)
      .update(Buffer.from([round]))
      .update(right)
      .digest()
      .subarray(0, LOGIN_CODE_HALF_BYTES);
    const nextRight = Buffer.alloc(LOGIN_CODE_HALF_BYTES);
    for (let index = 0; index < LOGIN_CODE_HALF_BYTES; index += 1) {
      nextRight[index] = left[index]! ^ mask[index]!;
    }
    left = right;
    right = nextRight;
  }
  return encodeBase32(Buffer.concat([left, right]));
}

export function incrementLoginCodeCounter(counter: Uint8Array): Buffer | null {
  if (counter.byteLength !== LOGIN_CODE_COUNTER_BYTES) {
    throw new Error("Login code counter must contain 10 bytes");
  }
  const next = Buffer.from(counter);
  for (let index = next.length - 1; index >= 0; index -= 1) {
    if (next[index] !== 0xff) {
      next[index]! += 1;
      return next;
    }
    next[index] = 0;
  }
  return null;
}

export async function hashPassword(password: string): Promise<string> {
  const salt = randomBytes(16);
  const result = await scrypt(password, salt, PASSWORD_KEY_LENGTH, {
    N: PASSWORD_N,
    r: PASSWORD_R,
    p: PASSWORD_P,
    maxmem: 64 * 1024 * 1024,
  });
  return [
    "scrypt",
    PASSWORD_N,
    PASSWORD_R,
    PASSWORD_P,
    salt.toString("base64url"),
    result.toString("base64url"),
  ].join("$");
}

export async function verifyPassword(password: string, encoded: string): Promise<boolean> {
  const [algorithm, nRaw, rRaw, pRaw, saltRaw, keyRaw] = encoded.split("$");
  if (algorithm !== "scrypt" || !saltRaw || !keyRaw) return false;
  const N = Number(nRaw),
    r = Number(rRaw),
    p = Number(pRaw);
  if (N !== PASSWORD_N || r !== PASSWORD_R || p !== PASSWORD_P) return false;
  const expected = Buffer.from(keyRaw, "base64url");
  const actual = await scrypt(password, Buffer.from(saltRaw, "base64url"), expected.length, {
    N,
    r,
    p,
    maxmem: 64 * 1024 * 1024,
  });
  return actual.length === expected.length && timingSafeEqual(actual, expected);
}

export function constantEqual(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left),
    rightBytes = Buffer.from(right);
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function scrypt(
  password: string,
  salt: Buffer,
  length: number,
  options: { N: number; r: number; p: number; maxmem: number },
): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    scryptCallback(password, salt, length, options, (error, result) => {
      if (error) reject(error);
      else resolve(result);
    });
  });
}

function encodeBase32(value: Uint8Array): string {
  let accumulator = 0;
  let bits = 0;
  let result = "";
  for (const byte of value) {
    accumulator = (accumulator << 8) | byte;
    bits += 8;
    while (bits >= 5) {
      bits -= 5;
      result += CODE_ALPHABET[(accumulator >>> bits) & 31];
      accumulator &= (1 << bits) - 1;
    }
  }
  if (bits !== 0) throw new Error("Base32 input must contain a whole number of symbols");
  return result;
}
