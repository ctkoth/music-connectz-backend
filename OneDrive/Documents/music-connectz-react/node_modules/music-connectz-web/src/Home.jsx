import React from 'react';
import SocialFeed from './SocialFeed';

export default function Home() {
  return (
    <div style={{ maxWidth: 700, margin: '0 auto', padding: 32 }}>
      <SocialFeed />
      <h1 style={{ fontSize: 32, fontWeight: 700, margin: '32px 0 16px' }}>Welcome to MusicConnectZ</h1>
      <div style={{ fontSize: 18, color: '#444', marginBottom: 32 }}>
        Discover, collaborate, and compete in music battles. Try the new Battles feature and see what’s trending!
      </div>
      {/* ...other homepage content... */}
    </div>
  );
}
