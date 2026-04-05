## v12.3 Add 'ParcelPrimate 🦍' as a Mailchimp knockoff to Premium Apps

- **ParcelPrimate 🦍**
	“Go bananas with your email campaigns! ParcelPrimate is the Corey-voice remix of Mailchimp—build, blast, and track your newsletters, drops, and fan updates. Drag, drop, and deliver your message with style. No monkey business, just pure engagement. Premium users get advanced analytics, automation, and the wildest templates in the jungle.”

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

---

## v11.5 Plan: Corey Voice ConnectZ Tab & Export

- Add a new tab in the UI: “Corey Voice ConnectZ”
  - Access chat, image, and file generation features
  - Only available to premium users (with upgrade prompt for others)
- Allow users to export generated files (text, images) directly to their posts
  - After generating, show “Export to Post” and “Download” buttons
  - Pre-fill post creation form with generated content or trigger file download (txt, png, etc.)
- Version bump: v11.5
  - Update version labels and changelog

---

## v11.6 Features: Automated Collab Royalty Agreements

- Auto-suggest royalty splits for collaborations based on each collaborator’s skill prices and actual skills used on the work.
- Editable royalty agreement draft: all collaborators can propose changes to splits/terms before finalization.
- Approval workflow: all collaborators must explicitly approve the final agreement before it is locked.
- Audit trail: all changes and approvals are logged for transparency.
- API endpoints for:
  - Generating and retrieving draft/final agreements
  - Editing and approving agreements
  - Viewing audit/change history
- Frontend UI for:
  - Displaying suggested splits and agreement text
  - Allowing edits and showing real-time updates
  - Requiring all approvals before finalization
  - Displaying audit trail of changes/approvals

---

## v11.7 Add 'ScoreZ 🔟' as a new app for user attractiveness ratings, with Corey-voice description, to the MVP plan.

- **ScoreZ 🔟**
  “Let the people decide! ScoreZ lets users rate each other’s attractiveness on a scale of 1 to 10—no filters, no cap, just real feedback. Flex your confidence, see where you stand, and maybe find your next crush or collab. It’s all love, all vibes, all ScoreZ.”

---

## UGC Sharing for All Apps 🌐
- “Every app, every vibe—now shareable on musicconnectz.net and beyond! All user-generated content (UGC) can be posted, linked, and flexed online. Drop your beats, scores, collabs, and even your ScoreZ ratings for the world to see. Go viral, get feedback, and let your creativity travel. If you made it, you can share it—no gatekeeping, just pure expression.”

---

## v11.8 Add 'ScoreZ Visibility Controls 👁️'

- **ScoreZ Visibility Controls 👁️**
  “You call the shots! On ScoreZ, users can set their attractiveness score visibility to public (anyone can see), private (only you), or restricted (friends/collabs only). Flex your confidence, keep it low-key, or share with your inner circle—your score, your rules, your vibe.”

---

## v11.9 Add 'Easter ✝️' as a backup app knockoff with Corey-voice description to the MVP plan.

- **Easter ✝️**
  “Resurrect your files, never lose a vibe. Easter is your backup miracle—auto-save, one-click restore, and cloud peace of mind. Keep your tracks, projects, and collabs safe, share with your crew, or keep ‘em locked down. Your music, your moves, your backup—blessed and protected.”

---

Let me know if you want backend or frontend code samples for any of these steps!

- **Monday.com** → “Sturday 🪩” (weekly goals, music drops, progress bars)
- **Sonday** → “Sonday 👦🏾” (rest day, chill collab, share your wins, and recharge with the crew)
- **Liliths 💃🏾**  
  “Unleash your wild side. Liliths is for the creators who move different—bold, intuitive, and always in their own rhythm. Drop your ideas, remix your reality, and dance like nobody’s watching. This is goddess mode, activated.")
- **Infeno 🔥**
  “Swipe, match, and spark something wild. Infeno is the Corey-voice remix of Tinder—where the heat is real, the vibes are bold, and every match could be your next collab, crush, or creative partner. Shoot your shot, drop a beat, or just set the chat on fire. No games, just flames.”
