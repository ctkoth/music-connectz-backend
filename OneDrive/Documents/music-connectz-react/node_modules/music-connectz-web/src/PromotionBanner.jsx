// PromotionBanner.jsx
import React from 'react';

export default function PromotionBanner({ isActiveUser }) {
  if (!isActiveUser) return null;
  return (
    <div style={{
      background: '#ffe066',
      color: '#222',
      padding: '18px 0',
      borderRadius: 10,
      margin: '24px 0',
      fontWeight: 600,
      fontSize: 20,
      textAlign: 'center',
      boxShadow: '0 2px 8px #0001',
    }}>
      🎉 Thanks for being active! Enjoy 20% off your next month of Premium with code <b>LOYAL20</b> 🎉
    </div>
  );
}
