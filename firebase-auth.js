// firebase-auth.js
// Add Firebase Authentication to your app
// Requires firebase-app.js, firebase-auth.js, firebase-config.js, and firebase-init.js to be loaded first


const BACKEND_URL = 'https://admin.musicconnectz.net';

// Sign up using backend (Django API)
function signUp(email, password, name) {
  return fetch(`${BACKEND_URL}/api/auth/register/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      username: name,
      email: email,
      password1: password,
      password2: password
    }),
  })
    .then(async (response) => {
      const data = await response.json();
      if (!response.ok) {
        alert((data && (data.error || data.detail || JSON.stringify(data))) || 'Sign up failed');
        throw new Error((data && (data.error || data.detail || JSON.stringify(data))) || 'Sign up failed');
      }
      alert('Sign up successful!');
      return data;
    });
}

// Sign in using backend
function signIn(email, password) {
  return fetch(`${BACKEND_URL}/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ email, password }),
  })
    .then(async (response) => {
      if (!response.ok) {
        const error = await response.json();
        alert(error.error || 'Sign in failed');
        throw new Error(error.error || 'Sign in failed');
      }
      alert('Sign in successful!');
      return response.json();
    });
}

// Sign out (client-side only, since backend is stateless)
function signOut() {
  // If you use tokens/cookies, clear them here
  alert('Signed out!');
}
