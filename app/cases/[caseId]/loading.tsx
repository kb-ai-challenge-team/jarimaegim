import { LoaderCircle } from "lucide-react";

export default function CaseWorkspaceLoading() {
  return (
    <main className="workspace-loading" aria-live="polite" aria-busy="true">
      <div className="brand-symbol">터</div>
      <LoaderCircle className="spin" aria-hidden="true"/>
      <strong>의사결정 워크스페이스를 여는 중입니다</strong>
      <p>저장된 조건을 먼저 불러오고, 입지 근거는 이어서 표시합니다.</p>
    </main>
  );
}
