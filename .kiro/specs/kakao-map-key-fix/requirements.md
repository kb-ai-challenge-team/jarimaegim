# Requirements Document

## Introduction

This specification covers only the mandatory Kakao Maps configuration repair for the existing Ter Doctor Next.js application. The repair replaces the malformed local public map key value, conditionally verifies or configures authorized Kakao Web origins, synchronizes production on the designated EC2 host, rebuilds and restarts the frontend, and validates SDK loading without disclosing key material. Optional integrations and unrelated source or configuration remain outside scope.

## Glossary

- **Map_Fix_Procedure**: The complete local and production configuration repair workflow defined by this specification.
- **Local_Environment**: The ignored project environment file used to build the application on the developer workstation.
- **Production_Environment**: The frontend environment configuration used to build the application in `/home/ec2-user/ter-doctor` on the designated EC2 host.
- **JavaScript_Key**: The user-provided Kakao Maps JavaScript key assigned to `NEXT_PUBLIC_KAKAO_MAP_JS_KEY`; the value is browser-visible by platform design but must be redacted from logs, specifications, and reports.
- **Authorized_Kakao_Access**: Existing user-authorized access to the Kakao Developers application settings, without creating or guessing credentials.
- **Origin_Configuration_Procedure**: The authorized verification or update of Kakao Web platform origins.
- **Required_Origins**: `http://127.0.0.1:4173` and `http://jarimaegim.duckdns.org`.
- **Production_Host**: EC2 host `13.125.18.54`, accessed as `ec2-user` with the SSH identity file `/Users/jiwon/security/kb-ai.pem`.
- **Frontend_Service**: The `ter-doctor-web.service` systemd unit that runs the production Next.js server.
- **SDK_Load_Validation**: A browser-based check that confirms the Kakao Maps SDK request succeeds and the Maps namespace initializes while suppressing URL query values and key material.
- **Protected_Settings**: `SUPABASE_JWT_SECRET`, `SES_FROM_EMAIL`, the FinLife endpoint configuration, and every unrelated code or configuration value.

## Requirements

### Requirement 1: Correct the local map key configuration

**User Story:** As an application operator, I want the local map key corrected, so that the local Next.js build can request the Kakao Maps SDK.

#### Acceptance Criteria

1. WHEN the user supplies the JavaScript_Key, THE Map_Fix_Procedure SHALL replace only the `NEXT_PUBLIC_KAKAO_MAP_JS_KEY` value in the Local_Environment.
2. WHEN the Local_Environment update completes, THE Map_Fix_Procedure SHALL verify that the configured value is non-empty and is not an HTTP or HTTPS URL without printing the configured value.
3. IF the JavaScript_Key is unavailable, THEN THE Map_Fix_Procedure SHALL stop before modifying local or production configuration and report the missing input without displaying environment values.

### Requirement 2: Protect key material and unrelated settings

**User Story:** As a security-conscious operator, I want sensitive values and unrelated settings protected, so that the map repair does not broaden configuration exposure or change scope.

#### Acceptance Criteria

1. WHILE executing the Map_Fix_Procedure, THE Map_Fix_Procedure SHALL redact the JavaScript_Key from command output, logs, generated artifacts, and completion reports.
2. WHEN any configuration update completes, THE Map_Fix_Procedure SHALL preserve every Protected_Setting byte-for-byte.
3. THE Map_Fix_Procedure SHALL preserve unrelated source files and configuration entries.

### Requirement 3: Ensure authorized Kakao Web origins

**User Story:** As an application operator, I want the required Web origins authorized, so that Kakao accepts SDK requests from local and production pages.

#### Acceptance Criteria

1. WHERE Authorized_Kakao_Access is available, THE Origin_Configuration_Procedure SHALL verify that every Required_Origin is registered for the Kakao application associated with the JavaScript_Key.
2. WHERE Authorized_Kakao_Access is available, WHEN a Required_Origin is absent, THE Origin_Configuration_Procedure SHALL add the absent Required_Origin without removing existing origins.
3. IF Authorized_Kakao_Access is unavailable, THEN THE Origin_Configuration_Procedure SHALL report origin verification as blocked without claiming success or creating credentials.

### Requirement 4: Synchronize production configuration

**User Story:** As an application operator, I want production to use the same approved map key, so that local and deployed builds use the intended Kakao application.

#### Acceptance Criteria

1. WHEN local configuration validation succeeds, THE Map_Fix_Procedure SHALL connect to the Production_Host through the specified SSH user and identity file.
2. WHEN the production environment location is confirmed, THE Map_Fix_Procedure SHALL replace only the production `NEXT_PUBLIC_KAKAO_MAP_JS_KEY` value with the JavaScript_Key.
3. WHEN the production update completes, THE Map_Fix_Procedure SHALL verify local and production key equality through a non-reversible digest comparison without printing either value.
4. IF the production environment location cannot be confirmed, THEN THE Map_Fix_Procedure SHALL stop before rebuilding or restarting the Frontend_Service and report the blocked condition.

### Requirement 5: Rebuild and restart the production frontend

**User Story:** As an application operator, I want the production frontend rebuilt and restarted, so that the build-time public environment value is embedded in the active Next.js build.

#### Acceptance Criteria

1. WHEN production configuration synchronization succeeds, THE Map_Fix_Procedure SHALL execute the existing Next.js production build in `/home/ec2-user/ter-doctor`.
2. WHEN the production build succeeds, THE Map_Fix_Procedure SHALL restart the Frontend_Service.
3. WHEN the Frontend_Service restart completes, THE Map_Fix_Procedure SHALL verify that the Frontend_Service is active and the production HTTP origin responds successfully.
4. IF the production build fails, THEN THE Map_Fix_Procedure SHALL preserve the existing running Frontend_Service process and report the build failure without printing environment values.

### Requirement 6: Validate Kakao Maps SDK loading

**User Story:** As an application operator, I want non-secret SDK validation, so that the repair is proven without exposing key material.

#### Acceptance Criteria

1. WHEN the local application is built and available at the local Required_Origin, THE SDK_Load_Validation SHALL confirm that the Kakao Maps SDK request returns a successful response and initializes `window.kakao.maps`.
2. WHEN the rebuilt application is available at the production Required_Origin, THE SDK_Load_Validation SHALL confirm that the Kakao Maps SDK request returns a successful response and initializes `window.kakao.maps`.
3. WHILE recording SDK_Load_Validation results, THE SDK_Load_Validation SHALL omit query strings, request bodies, environment values, and JavaScript_Key content.
4. IF an SDK request is rejected because of an unauthorized origin, THEN THE SDK_Load_Validation SHALL identify the affected origin and a redacted failure category without recording the SDK request URL.