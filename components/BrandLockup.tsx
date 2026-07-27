import Link from "next/link";

// 로고 락업은 헤더·히어로·푸터 세 곳에서 크기와 태그라인 유무만 다르게 쓰인다.
// 심볼은 .brand-symbol 이 /icon.png 를 깔아 주므로 여기서 에셋을 직접 참조하지 않는다.
type Props = { size?: "sm" | "lg"; tagline?: boolean; href?: string };

export function BrandLockup({ size = "sm", tagline = false, href }: Props) {
  const body = <>
    <span className="brand-symbol" aria-hidden="true" />
    <span className="brand-words"><strong><b>KB</b> 자리매김</strong>{tagline && <small>더 나은 입지 선택을 위한 AI 파트너</small>}</span>
  </>;
  if (href) return <Link href={href} className="brand-lockup" data-size={size} aria-label="KB 자리매김 홈">{body}</Link>;
  return <span className="brand-lockup" data-size={size}>{body}</span>;
}
