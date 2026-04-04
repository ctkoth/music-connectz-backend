# Music Distribution MVP Plan (Ditto/Other Distributors)

## Goal
Enable users to submit releases from the app and track distributor delivery status (queued, processing, delivered, failed).

## Current State
- App has auth, profile, collaboration, and payments.
- App does not currently support DSP distribution workflows.
- No distributor API integration exists yet.

## Integration Strategy
1. Start with one distributor partner that exposes a usable API/webhook model.
2. Build a provider-agnostic internal release model.
3. Add one adapter implementation (e.g., Ditto-like adapter) behind a common interface.
4. Expand to additional providers after first integration is stable.

## Backend Data Model (MVP)

### DistributionAccount
- user (FK)
- provider (choices: ditto, generic_partner, etc)
- external_account_id
- status (active, pending, disconnected)
- scopes_granted
- access_token_encrypted
- refresh_token_encrypted
- token_expires_at
- created_at
- updated_at

### Release
- user (FK)
- title
- version_title
- primary_artist
- release_type (single, ep, album)
- genre
- language
- explicit
- upc (nullable)
- planned_release_date
- original_release_date (nullable)
- cover_art_file
- status (draft, submitted, processing, delivered, failed)
- provider (nullable until submitted)
- provider_release_id (nullable)
- validation_errors_json
- created_at
- updated_at

### Track
- release (FK)
- sequence_number
- title
- featured_artists
- isrc (nullable)
- audio_file
- explicit
- duration_seconds
- composer_writers_json
- publisher_info_json
- lyrics_text (nullable)
- language

### ReleaseTerritory
- release (FK)
- mode (worldwide, include, exclude)
- territory_codes_json

### ReleaseSplit
- release (FK)
- payee_user (FK nullable)
- payee_email (fallback)
- percentage
- role (artist, producer, writer, label)

### DistributionJob
- release (FK)
- provider
- operation (create_release, update_release, deliver, takedown)
- request_payload_json
- response_payload_json
- status (queued, sent, succeeded, failed)
- error_code
- error_message
- retry_count
- created_at
- updated_at

### DistributionEvent
- release (FK)
- provider
- event_type
- event_time
- payload_json
- signature_valid
- processed

## API Endpoints (MVP)

### Account Linking
- POST /api/distribution/accounts/connect/
- GET /api/distribution/accounts/
- DELETE /api/distribution/accounts/{id}/

### Release Authoring
- POST /api/distribution/releases/
- GET /api/distribution/releases/
- GET /api/distribution/releases/{id}/
- PATCH /api/distribution/releases/{id}/
- POST /api/distribution/releases/{id}/tracks/
- PATCH /api/distribution/releases/{id}/tracks/{track_id}/

### Validation + Submission
- POST /api/distribution/releases/{id}/validate/
- POST /api/distribution/releases/{id}/submit/
- POST /api/distribution/releases/{id}/takedown/

### Status + Webhooks
- GET /api/distribution/releases/{id}/status/
- POST /api/distribution/webhooks/{provider}/

## Adapter Pattern
Create a provider adapter contract:
- validate_release(release) -> list[errors]
- submit_release(release) -> provider_release_id
- fetch_status(provider_release_id) -> normalized status
- takedown_release(provider_release_id) -> result
- verify_webhook(request) -> bool
- parse_webhook(request) -> normalized event

Implement first adapter in backend/adapters_distribution/<provider>.py.

## Security + Compliance
- Encrypt provider tokens at rest.
- Validate webhook signatures.
- Store immutable audit logs for submit/takedown.
- Require explicit user acceptance for rights ownership and revenue split terms.
- Add role-based checks so only release owner/authorized collaborators can submit.

## Billing Model Options
1. Per-release fee (one-time submit fee).
2. Subscription tier includes N releases per month.
3. Revenue-share model for premium distribution features.

## UX Flow (MVP)
1. User connects distributor account.
2. User creates release draft (metadata + cover).
3. User uploads tracks + optional ISRC/UPC.
4. User runs validation.
5. User submits release.
6. User watches timeline/status events.

## Phase Plan

### Phase 1 (2-3 weeks)
- Data models + migrations.
- Release CRUD APIs.
- Validation endpoint with internal rules only.
- Placeholder adapter + simulated statuses.

### Phase 2 (2-4 weeks)
- Real provider OAuth/account linking.
- Real submit/status/takedown adapter implementation.
- Webhook ingestion with signature verification.

### Phase 3 (1-2 weeks)
- Revenue splits UI/API.
- Retry queue and failure recovery dashboard.
- Audit and reporting endpoints.

## Acceptance Criteria (MVP)
- User can create and submit a release from app.
- System returns provider release id and normalized status.
- Failed submissions are visible with actionable errors.
- Webhooks update release status within 60 seconds.

## Recommended First Provider
- Use the first distributor with the clearest API + webhook docs and sandbox support.
- If Ditto partner API is unavailable, start with a provider that has public partner docs, then add Ditto adapter later.

## v11.3 Execution Notes (Ditto + Editable Submission Fields)

### Ditto Webhook Strategy (v11.3)
- Endpoint: `POST /api/distribution/webhooks/ditto/`
- Signature: verify `X-Ditto-Signature` using HMAC-SHA256 over raw request body with `DITTO_WEBHOOK_SECRET`.
- Dev fallback: allow unsigned payloads only when `DITTO_WEBHOOK_ALLOW_UNSIGNED=true`.
- Event resolution order:
	1. match by `provider_release_id`
	2. fallback to `local_release_id`
- Idempotency guard: skip duplicate event payloads for same release/provider/event_type/event_time.
- Status normalization:
	- failed/rejected/error -> `failed`
	- delivered/live/published/active -> `delivered`
	- processing/queued/pending/review -> `processing`
	- submitted/received -> `submitted`
- Persistence:
	- store every inbound webhook in `DistributionEvent`
	- store webhook processing audit row in `DistributionJob` (operation=`webhook_event`)

### Editable Submission Fields Process (v11.3)
- Endpoint: `GET|PATCH /api/distribution/releases/{id}/submission-fields/`
- Editable fields include:
	- title, version_title, primary_artist, release_type, genre, language, explicit, upc, planned_release_date, original_release_date
- Access rules:
	- draft releases: editable
	- submitted/processing/delivered: editable only with premium access
- On successful PATCH:
	- persist normalized values (trimmed genre/title fields, lowercased language code)
	- append `DistributionJob` audit row (operation=`update_release_fields`)

### Geo-Language Genre Support in App (v11.3)
- Frontend genre selector now builds options from:
	1. global major genres
	2. localized genre labels from the current i18n language pack
	3. language-root geo additions (for example: `pt-*`, `es-*`, `ja-*`)
- Outcome: users can submit using regional genres in their own language while keeping major catalog-compatible genres available.

### Testing Assets Added (v11.3)
- Python webhook sender: `scripts/test_ditto_webhook.py`
	- Sends HMAC-signed Ditto webhook payloads to `/api/distribution/webhooks/ditto/`
	- Example:
		- `python scripts/test_ditto_webhook.py --secret "<DITTO_WEBHOOK_SECRET>" --provider-release-id "local-1-1712234567" --status "delivered"`
- Postman collection: `postman/music-connectz-distribution-v11.3.postman_collection.json`
	- Includes requests for:
		- submission fields GET/PATCH
		- release status GET
		- signed Ditto webhook POST
	- Set collection variables before use: `base_url`, `release_id`, `provider_release_id`, `ditto_webhook_secret`
- Postman environment: `postman/music-connectz-distribution-v11.3.postman_environment.json`
	- Includes local + production URLs and `auth_cookie` for authenticated distribution endpoints.
