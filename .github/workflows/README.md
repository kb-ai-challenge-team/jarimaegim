# 파이프라인 설정

`ci.yml`은 설정 없이 바로 돈다. `deploy.yml`은 아래 값이 등록돼야 동작한다.

## Repository variables (Settings → Secrets and variables → Actions → Variables)

| 이름 | 값 |
| --- | --- |
| `DEPLOY_HOST` | `13.125.18.54` |
| `DEPLOY_USER` | `ec2-user` |
| `DEPLOY_PATH` | `/home/ec2-user/ter-doctor` |
| `DEPLOY_PUBLIC_URL` | `https://jarimaegim.duckdns.org` |

## Repository secrets

| 이름 | 만드는 법 |
| --- | --- |
| `DEPLOY_SSH_KEY` | `cat ~/security/kb-ai.pem` 전체 (`-----BEGIN`~`END-----` 포함) |
| `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan -t ed25519 13.125.18.54` 출력 중 `#` 주석이 아닌 줄 |

현재 호스트키는 아래와 같다. 인스턴스를 재생성하면 반드시 갱신해야 한다.

```
13.125.18.54 ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIP6K2YBgQylBU06K3p3koraIhxO5xRfGWUOv/yU4WsCn
```

## Environment

`production` 환경을 만들고 required reviewer를 지정하면 명세 §13.6의 배포 승인 게이트가 걸린다.
지정하지 않으면 main push마다 자동 배포된다.

## 전제 조건

- **보안 그룹에 22번 포트가 GitHub Actions 러너에서 접근 가능해야 한다.** 러너 IP는 고정되지 않으므로
  `0.0.0.0/0` 개방이 필요한데, 이는 보안 등급을 낮춘다. 대안은 아래 SSM 전환이다.
- `ec2-user`가 `systemctl restart ter-doctor-web|ter-doctor-api`를 비밀번호 없이 실행할 수 있어야 한다 (현재 충족).
- 서버 `.env`는 배포 대상이 아니다. rsync 제외 목록에 있으며 서버에서만 관리한다.

## SSM으로 전환하려면

명세 §13.6은 SSH 대신 GitHub OIDC + SSM Run Command를 권장한다. 인스턴스에 `amazon-ssm-agent`가
이미 active이므로 아래만 갖추면 된다.

1. AWS에 GitHub OIDC identity provider 등록 (`token.actions.githubusercontent.com`)
2. 이 저장소만 신뢰하는 IAM role 생성 (`ssm:SendCommand`, `s3:PutObject`)
3. EC2 인스턴스 프로파일에 `AmazonSSMManagedInstanceCore` 부여
4. 아티팩트 중계용 S3 버킷

전환 시 `deploy.yml`에서 바뀌는 건 **SSH 자격 준비 / 소스 동기화 / 원격 실행** 세 단계뿐이다.
릴리스 트리 생성, 체크섬, 롤백, 스모크 로직은 그대로 쓴다. 보안 그룹의 22번 포트는 닫을 수 있다.

## 의존성 오버라이드

`package.json`의 `overrides`는 next가 물고 오는 전이 의존성을 끌어올린 것이다.

| 패키지 | next 16.2.12 요구 | 강제 버전 | 이유 |
| --- | --- | --- | --- |
| `postcss` | `8.4.31` (고정) | `8.5.23` | XSS·임의 파일 읽기·경로 순회 3건 (`<=8.5.17` 취약) |
| `sharp` | `^0.34.5` | `0.35.3` | libvips CVE-2026-33327 외 (`<0.35.0` 취약) |

npm이 제시하는 자동 수정은 next를 9.3.3으로 내리는 semver-major 다운그레이드뿐이라 쓸 수 없다.
next가 두 패키지를 상향 호환으로 올리면 오버라이드를 지울 것. 지울 때는 `npm audit --omit=dev
--audit-level=high`가 여전히 통과하는지와 `npm run build`를 함께 확인한다.

## 롤백

자동 롤백은 직전 빌드 스냅샷(`.next.prev`)을 되돌린다. 소스는 새 커밋 상태로 남으므로
원인을 고친 뒤 다시 배포하거나, 이전 커밋으로 `workflow_dispatch`를 돌리면 된다.

수동 롤백:

```bash
ssh -i ~/security/kb-ai.pem ec2-user@13.125.18.54 \
  'cd /home/ec2-user/ter-doctor && mv .next .next.failed && mv .next.prev .next && sudo systemctl restart ter-doctor-web'
```
