# CI

`ci.yml`은 설정 없이 바로 돈다. 비밀값도 변수도 필요 없다.

| 잡 | 내용 |
| --- | --- |
| web | `npm ci` → lint → typecheck → kakao 도구 테스트 → build |
| api | Python 3.12 → `pip install` → `compileall` → pytest (`.env` 없이) |
| audit | `npm audit --omit=dev --audit-level=high` |

`package.json`의 `api:check` / `api:test`는 `backend/.venv`를 가리키므로 CI에서는 쓰지 않고
러너 파이썬을 직접 호출한다.

## 배포는 여기 없다

배포는 `scripts/deploy.sh`가 담당한다. 로컬에서 빌드해 커밋 트리와 `.next`를 EC2로 rsync하고
systemd를 재시작한다. 배포 워크플로를 두지 않는 이유는 두 가지다.

- 서버가 t3.small(2GB, 스왑 없음)이라 `next build`를 서버에서 돌릴 수 없다. 서비스하면서
  컴파일하면 메모리 스파이크가 "느려짐"이 아니라 "sshd가 fork하지 못하는 잠김"으로 끝난다.
  실제로 그렇게 호스트가 잠긴 적이 있다.
- 러너에서 빌드해 산출물을 보내는 방식은 가능하지만, GitHub Actions 러너 IP가 고정되지 않아
  보안 그룹 22번을 `0.0.0.0/0`으로 열어야 한다. 지금 규모에서 그 대가를 치를 이유가 없다.

나중에 자동 배포가 필요해지면 SSH 대신 SSM Run Command를 쓰는 편이 낫다. 인스턴스에
`amazon-ssm-agent`가 이미 active이므로 GitHub OIDC provider, IAM role, 인스턴스 프로파일
(`AmazonSSMManagedInstanceCore`)만 갖추면 되고 22번은 계속 닫아 둘 수 있다.

## 의존성 오버라이드

`package.json`의 `overrides`는 next가 물고 오는 전이 의존성을 끌어올린 것이다.

| 패키지 | next 16.2.12 요구 | 강제 버전 | 이유 |
| --- | --- | --- | --- |
| `postcss` | `8.4.31` (고정) | `8.5.23` | XSS·임의 파일 읽기·경로 순회 3건 (`<=8.5.17` 취약) |
| `sharp` | `^0.34.5` | `0.35.3` | libvips CVE-2026-33327 외 (`<0.35.0` 취약) |

npm이 제시하는 자동 수정은 next를 9.3.3으로 내리는 semver-major 다운그레이드뿐이라 쓸 수 없다.
이 오버라이드 덕분에 운영 의존성 취약점이 0건이고, 그래서 audit 잡을 차단 게이트로 둘 수 있다.
게이트가 깨지면 기준을 낮추지 말고 원인을 고칠 것 — 낮추는 순간 그 잡은 의미가 없어진다.

next가 두 패키지를 상향 호환으로 올리면 오버라이드를 지운다. 지울 때는
`npm audit --omit=dev --audit-level=high`가 여전히 통과하는지와 `npm run build`를 함께 확인한다.
