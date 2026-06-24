import { NextResponse, type NextRequest } from "next/server";
import { SESSION_COOKIE_NAME } from "@/lib/auth/cookie-name";

/**
 * Primera barrera para el área de socios `(portal)/portal/*`: comprueba la
 * PRESENCIA de la cookie de sesión en el edge (barato y sin acceso a Node
 * crypto). La verificación CRIPTOGRÁFICA real (firma HMAC + expiración) se hace
 * en `(portal)/portal/layout.tsx` (runtime Node) con `getMemberSession()`.
 *
 * El dashboard admin `(admin)/admin/*` se protege con Supabase Auth + rol staff
 * dentro de su propio layout.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname.startsWith("/portal")) {
    const hasCookie = request.cookies.has(SESSION_COOKIE_NAME);
    if (!hasCookie) {
      const loginUrl = new URL("/login", request.url);
      loginUrl.searchParams.set("next", pathname);
      return NextResponse.redirect(loginUrl);
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/portal/:path*"],
};
