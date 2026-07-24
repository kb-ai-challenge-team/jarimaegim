import { AuthView } from "@/components/AuthView";

export default async function AuthPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const { error } = await searchParams;
  return <AuthView callbackError={Boolean(error)}/>;
}
