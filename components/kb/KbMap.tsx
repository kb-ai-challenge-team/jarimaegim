"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, MapPinned } from "lucide-react";
import { loadKakaoMaps, type KakaoMapInstance, type KakaoMaps, type KakaoOverlay } from "@/lib/kakao";
import { EVIDENCE_BADGES } from "@/lib/constants";
import type { Candidate, DistrictSummary } from "@/lib/types";
import { manwon } from "@/lib/format";

const SEOUL_CENTER = { lat: 37.551668, lng: 126.9743216 };
type MapState = "loading" | "ready" | "missing" | "error";

/**
 * Builds the KB-style split pill: white label half + graded value half.
 *
 * Only the focused marker shows its name and lease terms. Measured on production, fifteen
 * full-width labels in one district pile into a 211x187px clump where every one overlaps
 * another and only the focused label is readable. Unfocused markers collapse to rank plus
 * grade, which is narrow enough to sit apart; the full detail stays one click away and is
 * always present in the candidate list beside the map.
 *
 * The aria-label carries the whole thing either way — the collapse is visual only.
 */
function markerNode(candidate: Candidate, rank: number, isFocused: boolean, onFocus: (id: string) => void) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "kb-marker";
  node.dataset.grade = candidate.evidence_grade;
  if (candidate.listing) node.dataset.demo = "true";
  if (isFocused) node.dataset.focused = "true"; else node.dataset.compact = "true";
  const listing = candidate.listing;
  const spoken = listing ? ` ${listing.area_m2}제곱미터 보증금 ${manwon(listing.deposit_krw)}원 월세 ${manwon(listing.monthly_rent_krw)}원 시연용 데이터` : "";
  node.setAttribute("aria-label", `${rank}. ${candidate.name} ${EVIDENCE_BADGES[candidate.evidence_grade]}${spoken}`);
  const head = document.createElement("span");
  head.className = "kb-marker-head";
  const name = document.createElement("span");
  name.className = "kb-marker-name";
  name.textContent = isFocused ? `${rank}. ${candidate.name}` : String(rank);
  const value = document.createElement("span");
  value.className = "kb-marker-value";
  value.textContent = candidate.evidence_grade;
  head.append(name, value);
  node.append(head);
  if (listing && isFocused) {
    const chip = document.createElement("span");
    chip.className = "kb-marker-demo";
    chip.textContent = "시연용";
    name.append(chip);
    const line = document.createElement("span");
    line.className = "kb-marker-terms";
    line.textContent = `${listing.area_m2}㎡ · 보 ${manwon(listing.deposit_krw)} / 월 ${manwon(listing.monthly_rent_krw)}`;
    node.append(line);
  }
  node.addEventListener("click", (event) => { event.stopPropagation(); onFocus(candidate.id); });
  return node;
}

/** Landing pin: one per covered district, before any condition is entered. */
function summaryNode(entry: DistrictSummary, onSelect: (district: string) => void) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = "kb-district-pin";
  node.setAttribute("aria-label", `${entry.district} 시연용 매물 ${entry.count}건, 월세 중앙값 ${manwon(entry.median_monthly_rent_krw)}원. 눌러서 매물 보기`);
  const name = document.createElement("strong");
  name.textContent = entry.district;
  const count = document.createElement("span");
  count.textContent = `${entry.count}건`;
  const rent = document.createElement("small");
  rent.textContent = `월 ${manwon(entry.median_monthly_rent_krw)}`;
  node.append(name, count, rent);
  node.addEventListener("click", (event) => { event.stopPropagation(); onSelect(entry.district); });
  return node;
}

export function KbMap({ candidates, summary, focused, onFocus, onSelectDistrict, aiActive }: { candidates: Candidate[]; summary: DistrictSummary[]; focused: string | null; onFocus: (id: string) => void; onSelectDistrict: (district: string) => void; aiActive: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<KakaoMapInstance | null>(null);
  const mapsRef = useRef<KakaoMaps | null>(null);
  const overlaysRef = useRef<KakaoOverlay[]>([]);
  const summaryOverlaysRef = useRef<KakaoOverlay[]>([]);
  const key = process.env.NEXT_PUBLIC_KAKAO_MAP_JS_KEY;
  const [state, setState] = useState<MapState>(key ? "loading" : "missing");

  useEffect(() => {
    if (!key || !containerRef.current) return;
    let cancelled = false;
    loadKakaoMaps(key).then((maps) => {
      if (cancelled || !containerRef.current) return;
      mapsRef.current = maps;
      mapRef.current = new maps.Map(containerRef.current, { center: new maps.LatLng(SEOUL_CENTER.lat, SEOUL_CENTER.lng), level: 6 });
      setState("ready");
    }).catch(() => { if (!cancelled) setState("error"); });
    return () => { cancelled = true; };
  }, [key]);

  // Kakao caches tile geometry, so a container resize (panel toggle, breakpoint change) needs relayout.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || state !== "ready") return;
    const observer = new ResizeObserver(() => mapRef.current?.relayout());
    observer.observe(container);
    return () => observer.disconnect();
  }, [state]);

  // Rebuild overlays whenever the recommendation set or the focused candidate changes.
  useEffect(() => {
    const maps = mapsRef.current, map = mapRef.current;
    if (!maps || !map) return;
    overlaysRef.current.forEach((overlay) => overlay.setMap(null));
    overlaysRef.current = candidates.map((candidate, index) => {
      const isFocused = candidate.id === focused;
      const overlay = new maps.CustomOverlay({
        position: new maps.LatLng(candidate.latitude, candidate.longitude),
        content: markerNode(candidate, index + 1, isFocused, onFocus),
        yAnchor: 1.15, zIndex: isFocused ? 90 : 10, clickable: true
      });
      overlay.setMap(map);
      return overlay;
    });
    if (candidates.length > 0) {
      const bounds = new maps.LatLngBounds();
      candidates.forEach((candidate) => bounds.extend(new maps.LatLng(candidate.latitude, candidate.longitude)));
      if (!bounds.isEmpty()) map.setBounds(bounds, 80, 80, 80, 80);
    }
  }, [candidates, focused, onFocus, state]);

  // District summary pins. Cleared as soon as candidates exist, so the two pin kinds
  // never share the map.
  useEffect(() => {
    const maps = mapsRef.current, map = mapRef.current;
    if (!maps || !map) return;
    summaryOverlaysRef.current.forEach((overlay) => overlay.setMap(null));
    summaryOverlaysRef.current = [];
    if (candidates.length > 0 || summary.length === 0) return;
    summaryOverlaysRef.current = summary.map((entry) => {
      const overlay = new maps.CustomOverlay({
        position: new maps.LatLng(entry.latitude, entry.longitude),
        content: summaryNode(entry, onSelectDistrict), yAnchor: 1.1, zIndex: 20, clickable: true
      });
      overlay.setMap(map);
      return overlay;
    });
    const bounds = new maps.LatLngBounds();
    summary.forEach((entry) => bounds.extend(new maps.LatLng(entry.latitude, entry.longitude)));
    if (!bounds.isEmpty()) map.setBounds(bounds, 100, 100, 100, 100);
  }, [summary, candidates.length, onSelectDistrict, state]);

  useEffect(() => {
    const maps = mapsRef.current, map = mapRef.current;
    if (!maps || !map || !focused) return;
    const target = candidates.find((candidate) => candidate.id === focused);
    if (target) map.setCenter(new maps.LatLng(target.latitude, target.longitude));
  }, [focused, candidates]);

  return <div className="kb-map">
    <div ref={containerRef} className="kb-map-canvas" aria-hidden={state !== "ready"} />
    {state !== "ready" && <div className="kb-map-fallback">
      {state === "error" ? <AlertTriangle aria-hidden="true" /> : <MapPinned aria-hidden="true" />}
      <strong>{state === "missing" ? "지도 연결 키가 필요합니다" : state === "error" ? "지도를 불러오지 못했습니다" : "지도를 불러오는 중입니다"}</strong>
      <p>{state === "missing" ? "Kakao JavaScript 키를 설정하면 지도에 추천 입지가 표시됩니다. 목록은 그대로 사용할 수 있습니다." : "추천 입지 목록은 왼쪽 패널에서 계속 확인할 수 있습니다."}</p>
    </div>}
    {state === "ready" && aiActive && candidates.length === 0 && <div className="kb-map-hint" role="status">
      <span className="kb-ai-dot" aria-hidden="true" />조건을 확정하면 이 지도에 추천 입지가 표시됩니다.
    </div>}
  </div>;
}
