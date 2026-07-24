import { Suspense } from "react";
import { Onboarding } from "@/components/Onboarding";
export default function NewCasePage(){ return <Suspense fallback={<main className="page-loading">조건 입력 화면을 준비하고 있습니다.</main>}><Onboarding/></Suspense>; }
