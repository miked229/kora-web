import "server-only";

import { cookies } from "next/headers";
import crypto from "crypto";
import { getServerEnv } from "@/lib/env";
import { SESSION_COOKIE_NAME } from "@/lib/auth/cookie-name";
import type { MemberSession } from "@/lib/types";

/**
 * Sesión de socio firmada con HMAC-SHA256 (formato compacto tipo JWT sin
 * dependencias externas). Se almacena en una cookie httpOnly/secure.
 *
 * NOTA: para producción con MFA/OTP, migrar a JWT estándar con rotación de
 * claves (JWKS). Este esquema cubre el MVP de forma segura y autocontenida.
 */

const COOKIE_NAME = SESSION_COOKIE_NAME;
const MAX_AGE_SECONDS = 60 * 60 * 8; // 8 horas

function base64url(input: Buffer | string) {
  return Buffer.from(input)
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function sign(payload: string, secret: string) {
  return base64url(crypto.createHmac("sha256", secret).update(payload).digest());
}

export function createSessionToken(
  data: Pick<MemberSession, "member_id" | "membership_no" | "full_name">,
): string {
  const { MEMBERSHIP_SESSION_SECRET } = getServerEnv();
  const now = Math.floor(Date.now() / 1000);
  const body: MemberSession = {
    ...data,
    iat: now,
    exp: now + MAX_AGE_SECONDS,
  };
  const payload = base64url(JSON.stringify(body));
  const signature = sign(payload, MEMBERSHIP_SESSION_SECRET);
  return `${payload}.${signature}`;
}

export function verifySessionToken(token: string): MemberSession | null {
  try {
    const { MEMBERSHIP_SESSION_SECRET } = getServerEnv();
    const [payload, signature] = token.split(".");
    if (!payload || !signature) return null;

    const expected = sign(payload, MEMBERSHIP_SESSION_SECRET);
    // Comparación en tiempo constante.
    if (
      signature.length !== expected.length ||
      !crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))
    ) {
      return null;
    }

    const session = JSON.parse(
      Buffer.from(payload, "base64").toString("utf8"),
    ) as MemberSession;

    if (session.exp < Math.floor(Date.now() / 1000)) return null;
    return session;
  } catch {
    return null;
  }
}

/** Escribe la cookie de sesión (en route handlers / server actions). */
export function setSessionCookie(token: string) {
  cookies().set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: MAX_AGE_SECONDS,
  });
}

export function clearSessionCookie() {
  cookies().delete(COOKIE_NAME);
}

/** Recupera la sesión del socio desde la cookie, o null si no es válida. */
export function getMemberSession(): MemberSession | null {
  const token = cookies().get(COOKIE_NAME)?.value;
  if (!token) return null;
  return verifySessionToken(token);
}

export { SESSION_COOKIE_NAME };
