// Runtime app configuration for frontend deployments.
// Set backendUrl to your deployed API host (no trailing slash).
window.MCZ_CONFIG = window.MCZ_CONFIG || {};
window.MCZ_CONFIG.backendUrl = 'https://music-connectz-backend-2.onrender.com';
window.MCZ_CONFIG.authEntryPath = '/accounts/login/';
// Emergency mode: route auth to backend-hosted pages until CORS is fully configured.
window.MCZ_CONFIG.forceBackendAuth = true;
