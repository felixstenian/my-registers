import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const ACCESS_COOKIE = 'access_token';

// Rotas protegidas por presença de cookie access. A validação real acontece
// no backend (SP-06): se o cookie for inválido, o app recebe 401 e faz redirect.
const PROTECTED_PREFIXES = ['/chat', '/days', '/weekly'];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const isProtected = PROTECTED_PREFIXES.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
  const hasAccess = request.cookies.has(ACCESS_COOKIE);

  if (isProtected && !hasAccess) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('next', pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (pathname === '/login' && hasAccess) {
    return NextResponse.redirect(new URL('/chat', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/chat/:path*', '/days/:path*', '/weekly/:path*', '/login'],
};
