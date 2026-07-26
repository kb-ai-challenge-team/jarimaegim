#!/usr/bin/env bash
# 로컬에서 빌드하고 산출물만 EC2로 보낸다.
#
# 서버(t3.small · 2GB · 스왑 없음)에서 `next build`를 돌리면 앱을 서비스하면서
# 컴파일하게 되어 메모리 스파이크가 난다. 스왑이 없으므로 스파이크는 "느려짐"이
# 아니라 "sshd 가 fork 하지 못하는 잠김"으로 끝난다. 그래서 빌드는 로컬에서 한다.
#
# 서버에는 git 도 .git 도 없다. rsync 로 커밋 트리와 .next 를 정확히 일치시킨다.
#
# 사용법:
#   scripts/deploy.sh              배포
#   scripts/deploy.sh --dry-run    무엇이 바뀌는지만 출력
set -euo pipefail

REMOTE_HOST="${DEPLOY_HOST:-13.125.18.54}"
REMOTE_USER="${DEPLOY_USER:-ec2-user}"
APP_DIR="${DEPLOY_PATH:-/home/ec2-user/ter-doctor}"
PUBLIC_URL="${DEPLOY_PUBLIC_URL:-https://jarimaegim.duckdns.org}"
SSH_KEY="${DEPLOY_SSH_KEY_PATH:-$HOME/security/kb-ai.pem}"
# 서버 nginx 가 /api/v1/ 을 직접 프록시하므로 이 값이 프로덕션 동작을 바꾸지는 않는다.
# 그래도 빌드에 구워지는 값이니 서버와 같게 맞춰 둔다.
BACKEND_INTERNAL_URL="${BACKEND_INTERNAL_URL:-http://127.0.0.1:8000}"

DRY_RUN=0
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_ROOT"
SSH_OPTS=(-i "$SSH_KEY" -o BatchMode=yes -o ConnectTimeout=20)
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

say() { printf '\n\033[1m>> %s\033[0m\n' "$1"; }

# ── 1. 사전 점검 ────────────────────────────────────────────────────────────
say "사전 점검"
[ -r "$SSH_KEY" ] || { echo "SSH 키를 읽을 수 없습니다: $SSH_KEY"; exit 1; }
BRANCH="$(git branch --show-current)"
[ "$BRANCH" = "main" ] || { echo "main 에서만 배포합니다 (현재: $BRANCH)"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "커밋되지 않은 변경이 있습니다."; exit 1; }
COMMIT="$(git rev-parse HEAD)"
git fetch -q origin main
if [ "$(git rev-parse origin/main)" != "$COMMIT" ]; then
  echo "HEAD 가 origin/main 과 다릅니다. 먼저 푸시하세요."; exit 1
fi
echo "  커밋 $COMMIT"

# ── 2. 로컬 검증 ────────────────────────────────────────────────────────────
say "로컬 검증"
npm run lint
npm run typecheck
npm run api:check
npm run api:test
npm run test:kakao-tools

# ── 3. 로컬 빌드 ────────────────────────────────────────────────────────────
say "로컬 빌드 (서버에서 빌드하지 않는다)"
BACKEND_INTERNAL_URL="$BACKEND_INTERNAL_URL" npm run build
[ -f .next/BUILD_ID ] || { echo ".next/BUILD_ID 가 없습니다. 빌드가 산출물을 만들지 못했습니다."; exit 1; }
echo "  BUILD_ID $(cat .next/BUILD_ID)"

# ── 4. 릴리스 트리 ──────────────────────────────────────────────────────────
say "릴리스 트리 구성"
git archive "$COMMIT" | tar -x -C "$STAGE"
# .next 는 gitignore 대상이라 archive 에 없다. 캐시는 서버에 필요 없으므로 뺀다.
mkdir -p "$STAGE/.next"
rsync -a --exclude 'cache/' .next/ "$STAGE/.next/"
echo "  파일 $(find "$STAGE" -type f | wc -l | tr -d ' ')개 · .next $(du -sh "$STAGE/.next" | cut -f1)"

EXCLUDES=(
  --exclude 'node_modules/' --exclude '.next.prev/' --exclude '.env' --exclude '.env.local'
  --exclude 'backend/.venv/' --exclude '.deploy-backups/' --exclude '.deploy-commit'
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude 'artifacts/' --exclude '.data/'
  --exclude '.next/cache/'
)

if [ "$DRY_RUN" = "1" ]; then
  say "dry-run — 변경 목록"
  rsync -rlzc --dry-run --itemize-changes --delete -e "ssh ${SSH_OPTS[*]}" \
    "${EXCLUDES[@]}" "$STAGE"/ "$REMOTE_USER@$REMOTE_HOST:$APP_DIR/"
  exit 0
fi

# ── 5. 서버 백업 ────────────────────────────────────────────────────────────
say "서버 백업"
ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "set -euo pipefail
  cd '$APP_DIR'
  TS=\$(date +%Y%m%d-%H%M%S); B=\".deploy-backups/\$TS\"; mkdir -p \"\$B\"
  tar -czf \"\$B/source.tar.gz\" --exclude=./node_modules --exclude=./.next --exclude=./.next.prev \\
    --exclude=./backend/.venv --exclude=./.deploy-backups --exclude=./.data \\
    --exclude=./artifacts --exclude='*__pycache__*' --exclude=./.env . 2>/dev/null
  cp -f .deploy-commit \"\$B/deploy-commit.txt\" 2>/dev/null || echo unknown > \"\$B/deploy-commit.txt\"
  rm -rf .next.prev && cp -a .next .next.prev
  echo \"  백업 \$TS · 이전 커밋 \$(cat \"\$B/deploy-commit.txt\")\"
  df -h / | tail -1 | awk '{print \"  디스크 여유 \"\$4}'"

# ── 6. 동기화 ───────────────────────────────────────────────────────────────
# 백엔드는 설정을 모듈 import 시점에 읽는다(policy_params 등). backend/ 또는 config/ 가
# 바뀌면 웹만 재시작해서는 반영되지 않으므로 API 도 함께 재시작해야 한다.
api_fingerprint() {
  ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" \
    "cd '$APP_DIR' 2>/dev/null && find backend/app config backend/requirements.txt -type f 2>/dev/null | sort | xargs md5sum 2>/dev/null | md5sum | cut -d' ' -f1 || echo none"
}
say "동기화"
LOCK_BEFORE="$(ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "md5sum '$APP_DIR/package-lock.json' 2>/dev/null | cut -d' ' -f1 || echo none")"
API_BEFORE="$(api_fingerprint)"
rsync -rlzc --delete -e "ssh ${SSH_OPTS[*]}" "${EXCLUDES[@]}" \
  "$STAGE"/ "$REMOTE_USER@$REMOTE_HOST:$APP_DIR/"
LOCK_AFTER="$(ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "md5sum '$APP_DIR/package-lock.json' | cut -d' ' -f1")"
API_AFTER="$(api_fingerprint)"

# ── 7. 의존성·재시작 ────────────────────────────────────────────────────────
say "의존성 · 재시작"
LOCK_CHANGED=0
[ "$LOCK_BEFORE" != "$LOCK_AFTER" ] && LOCK_CHANGED=1
API_CHANGED=0
[ "$API_BEFORE" != "$API_AFTER" ] && API_CHANGED=1
echo "  package-lock 변경: $LOCK_CHANGED · backend·config 변경: $API_CHANGED"
ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "set -euo pipefail
  cd '$APP_DIR'
  if [ '$LOCK_CHANGED' = '1' ]; then
    echo '  npm ci (빌드는 하지 않는다)'
    npm ci --no-audit --no-fund
  else
    echo '  package-lock 동일 — npm ci 생략'
  fi
  if [ '$API_CHANGED' = '1' ]; then
    echo '  restart api (backend·config 변경 — 설정을 import 시점에 읽는다)'
    sudo systemctl restart ter-doctor-api
    sleep 3
  else
    echo '  backend·config 동일 — api 재시작 생략'
  fi
  sudo systemctl restart ter-doctor-web
  sleep 4
  systemctl is-active ter-doctor-web ter-doctor-api nginx"

# ── 8. 검증 ─────────────────────────────────────────────────────────────────
say "검증"
FAILED=0
for path in /healthz /; do
  CODE="$(curl -s -o /dev/null -m 25 -w '%{http_code}' "$PUBLIC_URL$path" || echo 000)"
  printf '  %-10s %s\n' "$path" "$CODE"
  [ "$CODE" = "200" ] || FAILED=1
done
if [ "$FAILED" = "0" ]; then
  curl -s -m 25 "$PUBLIC_URL/api/v1/status" | python3 -c "
import sys, json
d = json.load(sys.stdin)
axes = d.get('axes') or {}
on = sum(1 for a in axes.values() if a['enabled'])
print(f'  axes {on}/{len(axes)} 가동')
if not axes: raise SystemExit('axes 가 없습니다 — 구 코드가 서빙되고 있습니다')
" || FAILED=1
fi

# ── 9. 실패 시 롤백 ─────────────────────────────────────────────────────────
if [ "$FAILED" != "0" ]; then
  say "검증 실패 — 이전 빌드로 롤백"
  ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "set -euo pipefail
    cd '$APP_DIR'
    if [ -d .next.prev ]; then rm -rf .next && mv .next.prev .next && sudo systemctl restart ter-doctor-web; echo '  이전 .next 로 되돌렸습니다';
    else echo '  .next.prev 가 없어 자동 롤백하지 못했습니다'; fi"
  echo "배포 실패."
  exit 1
fi

# ── 10. 배포 커밋 기록 ──────────────────────────────────────────────────────
ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "printf '%s' '$COMMIT' > '$APP_DIR/.deploy-commit'"
say "배포 완료 — $COMMIT"
