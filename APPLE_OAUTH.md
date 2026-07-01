# Sign in with Apple — setup (Apple Developer)

You need a paid Apple Developer account ($99/yr). Goal: get the values the backend
and frontend expect.

What the code uses:
- Frontend (`VITE_APPLE_CLIENT_ID`) = your **Services ID** (e.g. `net.musicconnectz.web`)
- Backend (`APPLE_OAUTH_CLIENT_ID`) = the **same Services ID** (it's the JWT audience)

The backend verifies Apple's identity token against Apple's public keys and checks
the audience == your Services ID, so these two MUST match.

## 1. App ID (identifier for your app)
1. developer.apple.com → Certificates, IDs & Profiles → Identifiers → +
2. Choose **App IDs** → App → Continue.
3. Description: "Music ConnectZ". Bundle ID (explicit): `net.musicconnectz.app`.
4. Scroll to Capabilities → check **Sign In with Apple** → Continue → Register.

## 2. Services ID (this is your CLIENT ID)
1. Identifiers → + → **Services IDs** → Continue.
2. Description: "Music ConnectZ Web". Identifier: `net.musicconnectz.web` → Register.
3. Open it → check **Sign In with Apple** → Configure:
   - Primary App ID: select `net.musicconnectz.app` from step 1.
   - **Domains and Subdomains**: `musicconnectz.net`, `www.musicconnectz.net`,
     and `ctkoth-music-connectz-frontend-wy3x.vercel.app`
   - **Return URLs**: `https://musicconnectz.net/oauth/callback`
     (add the vercel.app callback too if you test there)
   - Save → Continue → Save.
4. Your **Services ID** `net.musicconnectz.web` is the CLIENT ID for both
   `VITE_APPLE_CLIENT_ID` (Vercel) and `APPLE_OAUTH_CLIENT_ID` (Render).

## 3. (Only if you later do server-side token exchange) Key + Team ID
The current backend verifies the **identity token** Apple returns to the browser,
so you do NOT need a private key for basic login. If you ever add server-to-server
refresh, create a **Key** (Keys → + → Sign In with Apple), download the `.p8`
ONCE, and note the **Key ID** and your **Team ID** (top-right of the portal).
Those would become `APPLE_KEY_ID`, `APPLE_TEAM_ID`, `APPLE_PRIVATE_KEY` — not
required for what you have now.

## 4. Set the env vars
Render:  `APPLE_OAUTH_CLIENT_ID=net.musicconnectz.web`
Vercel:  `VITE_APPLE_CLIENT_ID=net.musicconnectz.web`
         `VITE_OAUTH_REDIRECT=https://musicconnectz.net/oauth/callback`

## 5. Test
Click "Continue with Apple" on the login page → Apple popup → on success the app
posts the identity token to `/api/auth/oauth/apple/` and you get a JWT back.

### Notes / gotchas
- Apple only returns the user's name on the FIRST authorization; email may be a
  private relay address. The backend handles missing name fine.
- The domain you sign in from must be in "Domains and Subdomains" or Apple errors.
- Return URL must EXACTLY match `VITE_OAUTH_REDIRECT`.
- Google: console.cloud.google.com → APIs & Services → Credentials → OAuth client
  ID (Web). Authorized JS origins = your site URLs. Use the Client ID for
  `VITE_GOOGLE_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_ID`.
- GitHub: github.com/settings/developers → New OAuth App. Authorization callback
  URL = `https://musicconnectz.net/oauth/callback`. Client ID →
  `VITE_GITHUB_CLIENT_ID` + `GITHUB_OAUTH_CLIENT_ID`; Client secret →
  `GITHUB_OAUTH_CLIENT_SECRET` (Render only).
