// PremiumCredits.jsx
import React, { useState } from 'react';
import StripeCheckoutButton from './StripeCheckoutButton';

// Replace with your actual Stripe Price IDs
const PRICES = {
  month: { id: 'price_monthly_id', label: '1 Month Premium', amount: '$9.99' },
  year: { id: 'price_yearly_id', label: '1 Year Premium', amount: '$89.99' },
};

export default function PremiumCredits() {
  const [selected, setSelected] = useState('month');

  return (
    <div style={{ maxWidth: 400, margin: '40px auto', padding: 32, background: '#fff', borderRadius: 12, boxShadow: '0 2px 12px #0001', textAlign: 'center' }}>
      <h2>Buy Premium Credits</h2>
      <div style={{ margin: '24px 0' }}>
        <label style={{ marginRight: 18 }}>
          <input type="radio" name="premium" value="month" checked={selected === 'month'} onChange={() => setSelected('month')} />
          {PRICES.month.label} ({PRICES.month.amount})
        </label>
        <label>
          <input type="radio" name="premium" value="year" checked={selected === 'year'} onChange={() => setSelected('year')} />
          {PRICES.year.label} ({PRICES.year.amount})
        </label>
      </div>
      <StripeCheckoutButton priceId={PRICES[selected].id} />
    </div>
  );
}
