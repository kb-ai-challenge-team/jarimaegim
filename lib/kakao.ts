// Shared Kakao Maps SDK loader. Kept free of `declare global` so it never collides
// with the narrower inline declaration in components/KakaoMap.tsx.

export interface KakaoLatLng { getLat(): number; getLng(): number }
export interface KakaoBounds { extend(point: KakaoLatLng): void; isEmpty(): boolean }
export interface KakaoMapInstance { setCenter(point: KakaoLatLng): void; setLevel(level: number): void; getLevel(): number; setBounds(bounds: KakaoBounds, paddingTop?: number, paddingRight?: number, paddingBottom?: number, paddingLeft?: number): void; relayout(): void }
export interface KakaoOverlay { setMap(map: KakaoMapInstance | null): void; setZIndex(value: number): void }
export interface KakaoMaps {
  load(callback: () => void): void;
  LatLng: new (lat: number, lng: number) => KakaoLatLng;
  LatLngBounds: new () => KakaoBounds;
  Map: new (container: HTMLElement, options: { center: KakaoLatLng; level: number }) => KakaoMapInstance;
  CustomOverlay: new (options: { position: KakaoLatLng; content: HTMLElement; yAnchor?: number; xAnchor?: number; zIndex?: number; clickable?: boolean }) => KakaoOverlay;
}

type KakaoWindow = Window & { kakao?: { maps: KakaoMaps } };
const SDK_URL = "https://dapi.kakao.com/v2/maps/sdk.js";
let pending: Promise<KakaoMaps> | null = null;

export function kakaoMaps(): KakaoMaps | null {
  if (typeof window === "undefined") return null;
  return (window as unknown as KakaoWindow).kakao?.maps ?? null;
}

export function loadKakaoMaps(key: string): Promise<KakaoMaps> {
  if (pending) return pending;
  const promise = new Promise<KakaoMaps>((resolve, reject) => {
    const ready = kakaoMaps();
    if (ready) { ready.load(() => resolve(ready)); return; }
    const script = document.createElement("script");
    script.src = `${SDK_URL}?appkey=${encodeURIComponent(key)}&autoload=false`;
    script.async = true;
    script.onload = () => { const maps = kakaoMaps(); if (!maps) { reject(new Error("kakao maps namespace missing")); return; } maps.load(() => resolve(maps)); };
    script.onerror = () => reject(new Error("kakao maps sdk failed to load"));
    document.head.appendChild(script);
  });
  pending = promise;
  promise.catch(() => { if (pending === promise) pending = null; });
  return promise;
}
