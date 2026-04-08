// RandomWeeklyPromoBanner.jsx
import React from 'react';

// Utility to determine if promo is active this week
function getWeeklyPromoWindow() {
  // Seed with current year and week number for deterministic randomness
  const now = new Date();
  const year = now.getUTCFullYear();
  const week = Math.floor((now - new Date(year, 0, 1)) / (7 * 24 * 60 * 60 * 1000));
  // Simple deterministic pseudo-random based on year+week
  const seed = year * 100 + week;
  // Random day (1=Mon, 7=Sun)
  const day = 1 + (seed % 7);
  // Random hour (0-19, so promo can start between 0:00 and 19:00 UTC)
  const hour = seed % 20;
  return { day, hour };
}

function isPromoActive() {
  const now = new Date();
  const { day, hour } = getWeeklyPromoWindow();
  // Is it the promo day and within the 4-hour window?
  return (
    now.getUTCDay() === day &&
    now.getUTCHours() >= hour &&
    now.getUTCHours() < hour + 4
  );
}

function getDayName(day) {
  return ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][day % 7];
}

export default function RandomWeeklyPromoBanner({ isActiveUser }) {
  const { day, hour } = getWeeklyPromoWindow();
  if (!isActiveUser) return null;
  if (!isPromoActive()) return null;
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
      🎉 Surprise Weekly Promo! This week, active users get <b>10% off</b> any Premium plan for 4 hours only:<br/>
      <b>{getDayName(day)} {hour}:00–{hour+4}:00 UTC</b>.<br/>
      Don’t miss out—this offer time changes every week! 🎉
    </div>
  );
}
