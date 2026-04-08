import React from 'react';
import SocialFeed from './src/SocialFeed';

const OAUTH_PROVIDERS = [
  'google',
  'facebook',
  'github',
  'linkedin',
  'microsoft',
  'soundcloud',
  'spotify',
  'tiktok',
  'twitter',
];

// Simple icon mapping (replace with actual SVGs or images in production)
const PROVIDER_ICONS = {
  google: '🔵',
  facebook: '📘',
  github: '🐙',
  linkedin: '💼',
  microsoft: '🪟',
  soundcloud: '☁️',
  spotify: '🎵',
  tiktok: '🎶',
  twitter: '🐦',
};

function OAuthProviderButton({ provider }) {
  function handleOAuth() {
    // Redirect to backend OAuth endpoint
    window.location.href = `https://admin.musicconnectz.net/accounts/${provider}/login/?process=login`;
  }
  return (
    <button
      onClick={handleOAuth}
      style={{
        margin: 8,
        minWidth: 120,
        minHeight: 48,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 18,
        fontWeight: 500,
        gap: 8,
        border: '1px solid #ddd',
        borderRadius: 6,
        background: '#fafbfc',
        cursor: 'pointer',
        boxShadow: '0 1px 2px rgba(0,0,0,0.03)'
      }}
    >
      <span style={{fontSize: 22}}>{PROVIDER_ICONS[provider]}</span>
      Sign in with {provider.charAt(0).toUpperCase() + provider.slice(1)}
    </button>
  );
}

import { useState } from 'react';

function TraditionalAuthFields({ isSignup }) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  async function handleSubmit(e) {
    e.preventDefault();
    setError('');
    setSuccess('');
    if (isSignup && password !== password2) {
      setError('Passwords do not match.');
      return;
    }
    try {
      const endpoint = isSignup ? '/accounts/signup/' : '/accounts/login/';
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(isSignup
          ? { username, password1: password, password2 }
          : { username, password }),
        credentials: 'include',
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || data.error || 'Registration/Login failed.');
      } else {
        setSuccess(isSignup ? 'Registration successful! Please log in.' : 'Login successful!');
      }
    } catch (err) {
      setError('Network error.');
    }
  }

  return (
    <form style={{ marginTop: 32, display: 'flex', flexDirection: 'column', gap: 12 }} onSubmit={handleSubmit}>
      <input
        placeholder="Email, Username, or Phone"
        style={{ minHeight: 40, fontSize: 16 }}
        value={username}
        onChange={e => setUsername(e.target.value)}
      />
      <input
        type="password"
        placeholder="Password"
        style={{ minHeight: 40, fontSize: 16 }}
        value={password}
        onChange={e => setPassword(e.target.value)}
      />
      {isSignup && (
        <input
          type="password"
          placeholder="Confirm Password"
          style={{ minHeight: 40, fontSize: 16 }}
          value={password2}
          onChange={e => setPassword2(e.target.value)}
        />
      )}
      {error && <div style={{ color: 'red', fontSize: 15 }}>{error}</div>}
      {success && <div style={{ color: 'green', fontSize: 15 }}>{success}</div>}
      <button type="submit" style={{ marginTop: 16, minHeight: 40, fontSize: 16 }}>
        {isSignup ? 'Sign Up' : 'Log In'}
      </button>
    </form>
  );
}

import { useState } from 'react';

export default function AuthScreen({ isSignup: isSignupProp = false }) {
  const [isSignup, setIsSignup] = useState(isSignupProp);
  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      justifyContent: 'center',
      alignItems: 'center',
      background: '#fff',
      padding: 24,
    }}>
      <SocialFeed />
      <h1 style={{ marginBottom: 12, fontWeight: 700, fontSize: 28 }}>
        MusicConnectZ Web App <span style={{fontSize:18, fontWeight:400, color:'#888'}}>(Web v16.0 | Mobile v1.0)</span>
      </h1>
      <div style={{
        marginBottom: 24,
        background: '#f5f5f5',
        borderRadius: 8,
        padding: '12px 18px',
        maxWidth: 520,
        fontSize: 16,
        color: '#333',
        fontStyle: 'italic',
        boxShadow: '0 1px 4px rgba(0,0,0,0.04)'
      }}>
        <span role="img" aria-label="Corey">🤖</span> Corey tip: Just let me know what you want to get done—one thing at a time or a whole list. I’ll remember, organize, and keep you on track. Ask for help anytime by clicking the <b>?</b>!
      </div>
      <div style={{
        width: '100%',
        maxWidth: 600,
        marginBottom: 32,
        border: '2px solid #635bff',
        borderRadius: 12,
        background: '#f6f8ff',
        boxShadow: '0 2px 8px #635bff22',
        padding: 24,
      }}>
        <div style={{
          fontWeight: 700,
          fontSize: 22,
          marginBottom: 12,
          textAlign: 'center',
          color: '#635bff',
        }}>
          <span role="img" aria-label="Corey">🤖</span> Sign in with your favorite provider for the fastest, most secure experience:
        </div>
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'center',
          gap: 12,
        }}>
          {OAUTH_PROVIDERS.map((provider) => (
            <OAuthProviderButton key={provider} provider={provider} />
          ))}
        </div>
      </div>
      <div style={{ width: '100%', maxWidth: 400, marginTop: 8 }}>
        <div style={{ textAlign: 'center', color: '#888', marginBottom: 8, fontWeight: 500 }}>
          or use manual {isSignup ? 'registration' : 'login'}:
        </div>
        <TraditionalAuthFields isSignup={isSignup} />
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          {isSignup ? (
            <>
              Already have an account?{' '}
              <button type="button" style={{ color: '#635bff', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: 16 }} onClick={() => setIsSignup(false)}>
                Log In
              </button>
            </>
          ) : (
            <>
              Need an account?{' '}
              <button type="button" style={{ color: '#635bff', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline', fontSize: 16 }} onClick={() => setIsSignup(true)}>
                Register
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
