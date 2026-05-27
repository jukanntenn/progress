import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PROXY_TARGET = process.env.BACKEND_URL || "http://127.0.0.1:5000";

export function proxy(request: NextRequest) {
  const targetUrl = new URL(
    request.nextUrl.pathname + request.nextUrl.search,
    PROXY_TARGET,
  );
  return NextResponse.rewrite(targetUrl);
}

export const config = {
  matcher: ["/api/:path*"],
};
