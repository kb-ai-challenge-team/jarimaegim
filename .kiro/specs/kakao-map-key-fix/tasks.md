# Implementation Plan: Kakao Map Key Fix

## Overview

Apply the approved Kakao JavaScript key locally and on the designated EC2 host, preserve unrelated configuration, rebuild the Next.js frontend, and validate both allowed origins without exposing key material. Use Node.js ESM for repository validation tooling and the existing SSH/systemd deployment conventions.

## Tasks

- [x] 1. Add narrowly scoped configuration safety tooling
  - [x] 1.1 Implement an exact environment-assignment updater
    - Add a repository script that accepts the key through masked input or process environment, rejects missing, URL-shaped, duplicate, or ambiguous values, atomically replaces only `NEXT_PUBLIC_KAKAO_MAP_JS_KEY`, and never prints values.
    - Preserve file permissions and verify fingerprints for all Protected Settings before and after updates.
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3_
  - [x] 1.2 Add focused updater tests
    - Cover valid replacement, URL rejection, missing input, duplicate assignments, unrelated-line preservation, and output redaction with fixture-only values.
    - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.3_

- [x] 2. Correct local configuration and handle Kakao origins
  - [x] 2.1 Apply the user-provided key to the local environment
    - Acquire the key without echoing the value, run the updater against the ignored local environment file, and confirm only the intended assignment changed.
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3_
  - [x] 2.2 Verify or configure the required Kakao Web origins
    - Using only existing Authorized Kakao Access, confirm or add `http://127.0.0.1:4173` and `http://jarimaegim.duckdns.org` without removing existing origins.
    - If authorized access is unavailable or an update is rejected, record the specific blocked or failed status without inventing credentials or claiming success.
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 3. Implement redacted SDK validation tooling
  - [x] 3.1 Add a Playwright SDK smoke-check script
    - Read the key from process memory, validate a supplied origin, confirm a successful Kakao SDK response and `window.kakao.maps`, and emit only sanitized booleans and failure categories.
    - Add a build-asset check that returns only whether the expected value was embedded.
    - _Requirements: 2.1, 6.1, 6.2, 6.3, 6.4_
  - [x] 3.2 Add sanitizer and result-shape tests
    - Verify query strings, environment assignments, and fixture key values cannot appear in normal or error output.
    - _Requirements: 2.1, 6.3, 6.4_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Synchronize and rebuild production
  - [x] 5.1 Update the confirmed production environment over SSH
    - Connect as `ec2-user` to `13.125.18.54` with `/Users/jiwon/security/kb-ai.pem`, confirm the environment file used by `/home/ec2-user/ter-doctor`, apply the exact updater, and compare local/remote key equality internally with non-reversible digests.
    - Stop without build or restart if SSH, environment discovery, scope checks, or digest equality fails.
    - _Requirements: 2.1, 2.2, 2.3, 4.1, 4.2, 4.3, 4.4_
  - [x] 5.2 Build and restart the Next.js frontend
    - Run `npm run build` in `/home/ec2-user/ter-doctor`; restart `ter-doctor-web.service` only after a successful build.
    - After restart completes, verify the service is active and the production HTTP origin responds successfully.
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [x] 6. Validate local and production SDK loading
  - [x] 6.1 Run the local redacted validation
    - Run the local build and asset check. Against an already available local server, run the SDK smoke check for `http://127.0.0.1:4173`; if unavailable, ask the user to run `npm run dev:web` manually before continuing.
    - Current result: build, asset embedding, local HTTP response, browser launch, origin registration, Kakao Maps activation, successful SDK response, and `window.kakao.maps` initialization all passed. The validator now loads the SDK in the disposable page's top-level document to match actual application behavior.
    - _Requirements: 6.1, 6.3, 6.4_
  - [x] 6.2 Run the production redacted validation and scope audit
    - Run the asset and SDK smoke checks for `http://jarimaegim.duckdns.org`, verify protected-setting fingerprints, and confirm repository changes contain no unrelated code or configuration.
    - Report origin status and sanitized pass/fail evidence without SDK URLs, query strings, digests, or environment values.
    - _Requirements: 2.1, 2.2, 2.3, 6.2, 6.3, 6.4_

- [x] 7. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Task Dependency Graph

```json
{
  "waves": [
    { "wave": 1, "tasks": ["1.1", "1.2"] },
    { "wave": 2, "tasks": ["2.1", "2.2", "3.1", "3.2"] },
    { "wave": 3, "tasks": ["4"] },
    { "wave": 4, "tasks": ["5.1", "5.2"] },
    { "wave": 5, "tasks": ["6.1", "6.2"] },
    { "wave": 6, "tasks": ["7"] }
  ]
}
```

## Notes

- Tasks marked with `*` are optional automated tests; configuration, deployment, and SDK validation remain mandatory.
- Do not modify `SUPABASE_JWT_SECRET`, `SES_FROM_EMAIL`, any FinLife endpoint setting, or unrelated code/configuration.
- Do not place the JavaScript key in task text, command arguments, logs, generated reports, or committed files.