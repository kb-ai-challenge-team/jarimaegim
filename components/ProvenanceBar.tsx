"use client";
import { useState } from "react";
import { ChevronDown, ShieldCheck } from "lucide-react";
import type { Provenance } from "@/lib/types";
import { formatCollectedAt } from "@/lib/constants";
const confidence={HIGH:"높음",MEDIUM:"보통",LOW:"낮음",INSUFFICIENT:"판단 불충분"} as const;
export function ProvenanceBar({data}:{data:Provenance}){const [open,setOpen]=useState(false);return <div className={`provenance ${open?"open":""}`}><button onClick={()=>setOpen(!open)} aria-expanded={open}><ShieldCheck/><span><strong>{data.source_name}</strong> · {data.source_as_of||"기준일 확인 필요"} · {data.spatial_unit} · 신뢰도 {confidence[data.confidence]}</span><ChevronDown/></button>{open&&<div className="provenance-detail"><dl><div><dt>업종 범위</dt><dd>{data.industry_scope}</dd></div><div><dt>자료 기준일</dt><dd>{data.source_as_of||"확인 필요"}</dd></div><div><dt>공개일</dt><dd>{data.published_at||"제공되지 않음"}</dd></div><div><dt>수집·검증</dt><dd>{formatCollectedAt(data.collected_at)} / {data.verified_at||"미검증"}</dd></div><div><dt>모델·룰</dt><dd>{data.model_version||"규칙 미적용"}</dd></div><div><dt>표본</dt><dd>{data.sample_n?`${data.sample_n.toLocaleString("ko-KR")}건`:"표시 가능한 표본 없음"}</dd></div></dl>{data.limitations.length>0&&<ul>{data.limitations.map(item=><li key={item}>{item}</li>)}</ul>}</div>}</div>}
