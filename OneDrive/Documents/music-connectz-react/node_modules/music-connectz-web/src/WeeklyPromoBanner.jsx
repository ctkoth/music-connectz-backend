// WeeklyPromoBanner.jsx
import React from 'react';

// Utility to check if the current time is within the weekly promo window
function isPromoActive() {
  // Promo starts every Monday at 12:00 UTC for 4 hours
  const now = new Date();
  const day = now.getUTCDay(); // 0 = Sunday, 1 = Monday, ...
  const hour = now.getUTCHours();
  // Only active on Mondays between 12:00 and 16:00 UTC
  return day === 1 && hour >= 12 && hour < 16;
}

export default function WeeklyPromoBanner({ isActiveUser }) {
  if (!isActiveUser || !isPromoActive()) return null;
  return (
    <div style={{
      background: '#c3f584',
      color: '#222',
      padding: '18px 0',
      borderRadius: 10,
      margin: '24px 0',
      fontWeight: 600,
      fontSize: 20,
      textAlign: 'center',
      boxShadow: '0 2px 8px #0001',
    }}>
      🎉 Weekly Flash Promo! For the next 4 hours, active users get <b>10% off</b> any Premium plan. Don’t miss out—this offer is only available once a week! 🎉
    </div>
  );
}
