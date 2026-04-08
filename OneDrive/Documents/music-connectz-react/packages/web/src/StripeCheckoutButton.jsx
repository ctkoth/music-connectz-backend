// StripeCheckoutButton.jsx
import React from 'react';

export default function StripeCheckoutButton({ priceId }) {
  const handleClick = async () => {
    const res = await fetch('/create-checkout-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ priceId }),
    });
    const data = await res.json();
    if (data.url) {
      window.location = data.url;
    } else {
      alert('Failed to start checkout: ' + (data.error || 'Unknown error'));
    }
  };

  return (
    <button onClick={handleClick} style={{ padding: '12px 24px', background: '#635bff', color: '#fff', border: 'none', borderRadius: 6, fontSize: 18, cursor: 'pointer' }}>
      Pay with Stripe
    </button>
  );
}
