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
  return (
    <button style={{
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
    }}>
      <span style={{fontSize: 22}}>{PROVIDER_ICONS[provider]}</span>
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
        <span role="img" aria-label="Corey">🤖</span> Corey tip: Just tell me what you want to get done—one thing at a time or a whole list. I’ll remember, organize, and keep you on track. Ask for help anytime by clicking the <b>?</b>!
      </div>
      <div style={{
        width: '100%',
        maxWidth: 600,
        marginBottom: 8,
      }}>
        <div style={{
          fontWeight: 600,
          fontSize: 20,
          marginBottom: 8,
          textAlign: 'center',
        }}>
          <span role="img" aria-label="Corey">🤖</span> I recommend signing in with one of these providers for the fastest, most secure experience:
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
      <TraditionalAuthFields isSignup={isSignup} />
    </div>
  );
}
