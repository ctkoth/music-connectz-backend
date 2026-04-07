import React from 'react';

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

function OAuthProviderButton({ provider }) {
  // Placeholder: Replace with actual icon and logic
  return (
    <button style={{ margin: 8, minWidth: 120, minHeight: 48 }}>
      Sign in with {provider.charAt(0).toUpperCase() + provider.slice(1)}
    </button>
  );
}

function TraditionalAuthFields({ isSignup }) {
  return (
    <form style={{ marginTop: 32, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <input placeholder="Email, Username, or Phone" style={{ minHeight: 40, fontSize: 16 }} />
      <input type="password" placeholder="Password" style={{ minHeight: 40, fontSize: 16 }} />
      {isSignup && (
        <input type="password" placeholder="Confirm Password" style={{ minHeight: 40, fontSize: 16 }} />
      )}
      <button type="submit" style={{ marginTop: 16, minHeight: 40, fontSize: 16 }}>
        {isSignup ? 'Sign Up' : 'Log In'}
      </button>
    </form>
  );
}

export default function AuthScreen({ isSignup = false }) {
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
      <h1 style={{ marginBottom: 12, fontWeight: 700, fontSize: 28 }}>
        MusicConnectZ Web App <span style={{fontSize:18, fontWeight:400, color:'#888'}}>(v15.8)</span>
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
        <span role="img" aria-label="Corey">🤖</span> Corey says: "You can tell me your tasks in order—just list what you want done, and I’ll manage and track them for you!"
      </div>
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        gap: 12,
        maxWidth: 600,
        width: '100%',
      }}>
        {OAUTH_PROVIDERS.map((provider) => (
          <OAuthProviderButton key={provider} provider={provider} />
        ))}
      </div>
      <TraditionalAuthFields isSignup={isSignup} />
    </div>
  );
}
