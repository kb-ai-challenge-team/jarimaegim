import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

function safeDestination(value: string | null) {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/cases";
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const destination = safeDestination(url.searchParams.get("next"));
  const code = url.searchParams.get("code");
  const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const origin = process.env.APP_ORIGIN || url.origin;
  if (!code || !supabaseUrl || !supabaseKey) {
    return NextResponse.redirect(new URL("/auth?error=callback_configuration", origin));
  }

  const cookieStore = await cookies();
  const supabase = createServerClient(supabaseUrl, supabaseKey, {
    cookies: {
      getAll: () => cookieStore.getAll(),
      setAll: (values) => values.forEach(({ name, value, options }) => cookieStore.set(name, value, options))
    }
  });
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) return NextResponse.redirect(new URL("/auth?error=callback_failed", origin));
  return NextResponse.redirect(new URL(destination, origin));
}
