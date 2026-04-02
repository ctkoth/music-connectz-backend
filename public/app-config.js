// Runtime app configuration for frontend deployments.
// Set backendUrl to your deployed API host (no trailing slash).
window.MCZ_CONFIG = window.MCZ_CONFIG || {};
window.MCZ_CONFIG.backendUrl = 'https://admin.musicconnectz.net';
window.MCZ_CONFIG.oauthBaseUrl = 'https://admin.musicconnectz.net';
window.MCZ_CONFIG.authEntryPath = '/accounts/login/';
// Browser key is public by design; restrict it by domain in Google Cloud Console.
window.MCZ_CONFIG.googleMapsApiKey = window.MCZ_CONFIG.googleMapsApiKey || '';
// Keep auth API-first on the frontend; avoid forced redirects to backend-hosted auth pages.
window.MCZ_CONFIG.forceBackendAuth = false;
