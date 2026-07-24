import { Workspace } from "@/components/Workspace";

export default async function CaseWorkspacePage({ params }: { params: Promise<{ caseId: string; section?: string[] }> }) {
  const { caseId, section } = await params;
  return <Workspace caseId={caseId} initialSection={(section || ["explore"]).join("/")} />;
}
