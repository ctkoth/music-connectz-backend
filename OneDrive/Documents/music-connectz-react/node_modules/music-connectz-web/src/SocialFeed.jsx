import React from 'react';

// Placeholder data for demo
const FEED = [
  { type: 'battle', user: 'DJ Nova', action: 'won a battle', target: 'The SoundSmiths', time: '2m ago' },
  { type: 'collab', user: 'LyricLyn', action: 'started a collab', target: 'with BeatBros', time: '10m ago' },
  { type: 'track', user: 'MC Flow', action: 'released a track', target: '"Skyline Dreams"', time: '20m ago' },
];

const ICONS = {
  battle: '⚔️',
  collab: '🤝',
  track: '🎵',
};

export default function SocialFeed() {
  return (
    <div style={{ background: '#fafaff', borderRadius: 12, padding: 20, margin: '24px 0', boxShadow: '0 2px 8px #0001', maxWidth: 500 }}>
      <h2 style={{ fontSize: 24, marginBottom: 16 }}>Live Feed</h2>
      {FEED.map((item, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', marginBottom: 14, fontSize: 18 }}>
          <span style={{ fontSize: 24, marginRight: 10 }}>{ICONS[item.type]}</span>
          <span><b>{item.user}</b> {item.action} <b>{item.target}</b> <span style={{ color: '#888', fontSize: 14 }}>· {item.time}</span></span>
        </div>
      ))}
    </div>
  );
}
