# Stripe Setup Guide for MusicConnectZ Membership System

## Overview
This guide explains how to set up Stripe products and prices for the MusicConnectZ membership tiers.

## Required Stripe Products & Prices

### 1. Premium Subscription Products

#### Premium Monthly Subscription
- **Product Name**: MusicConnectZ Premium - Monthly
- **Type**: Recurring
- **Billing Period**: Monthly
- **Price**: $4.99 USD
- **Price ID**: Create this in Stripe Dashboard → Products → Add Product
  - Copy the generated `price_xxxxx` ID
  - Replace `price_premium_monthly` in index.html with this ID

#### Premium Yearly Subscription
- **Product Name**: MusicConnectZ Premium - Yearly
- **Type**: Recurring
- **Billing Period**: Yearly
- **Price**: $39.99 USD (33% savings)
- **Price ID**: Create this in Stripe Dashboard → Products → Add Product
  - Copy the generated `price_xxxxx` ID
  - Replace `price_premium_yearly` in index.html with this ID

### 2. One-Time Purchase Products (Already Configured)

These use dynamic price creation, so no Price IDs needed:
- **Profile Boost** - $2.99 (7-day visibility boost)
- **Collaboration Unlock** - $0.99 (one extra collaboration slot)
- **Premium Badge** - $4.99 (verified badge, permanent)
- **Custom Themes** - $1.99 (unlock premium themes)

## Setup Steps

### Step 1: Create Stripe Products
1. Go to [Stripe Dashboard](https://dashboard.stripe.com/)
2. Navigate to **Products** → **Add Product**
3. Create the two Premium subscription products (monthly and yearly)
4. Copy the Price IDs generated for each

### Step 2: Configure Environment Variables
Add these to your `.env` file:

```bash
# Existing Stripe keys
STRIPE_SECRET_KEY=sk_test_xxxxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxxxx

# Webhook secret (for production)
STRIPE_WEBHOOK_SECRET=whsec_xxxxx

# Optional: Store Price IDs here instead of hardcoding
STRIPE_PRICE_PREMIUM_MONTHLY=price_xxxxx
STRIPE_PRICE_PREMIUM_YEARLY=price_xxxxx
```

### Step 3: Update Frontend Code
In `index.html`, find the `subscribePremium` function and replace the price IDs:

```javascript
const priceIds = {
  monthly: 'price_xxxxx', // Your actual monthly Price ID
  yearly: 'price_xxxxx'    // Your actual yearly Price ID
};
```

### Step 4: Configure Webhooks (Production)
1. In Stripe Dashboard, go to **Developers** → **Webhooks**
2. Add endpoint: `https://yourdomain.com/api/webhook`
3. Select events to listen for:
   - `checkout.session.completed`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
4. Copy the webhook signing secret to `.env` as `STRIPE_WEBHOOK_SECRET`

### Step 5: Test in Test Mode
1. Use Stripe test cards:
   - Success: `4242 4242 4242 4242`
   - Decline: `4000 0000 0000 0002`
2. Test subscription flow
3. Test one-time purchases
4. Verify webhook events are received

### Step 6: Go Live
1. Switch to live API keys in `.env`
2. Create live products with live prices
3. Update webhook endpoint with live URL
4. Test with real card (small amount)
5. Monitor Stripe Dashboard for transactions

## Membership Features Implementation

### FREE Tier (Default)
- ✓ Basic artist profiles
- ✓ 3 collaboration requests per month
- ✓ Standard search features
- ✓ View local musicians (GPS-based)

### PREMIUM Tier ($4.99/mo or $39.99/yr)
- ✓ Unlimited collaboration requests
- ✓ Advanced search filters
- ✓ Direct messaging
- ✓ Portfolio showcase with audio uploads
- ✓ "Featured Artist" status in searches
- ✓ Analytics dashboard

### In-App Purchases (One-Time)
- 🚀 Profile Boost - $2.99 (7-day feature)
- 🔓 Collaboration Unlock - $0.99 each
- ✅ Premium Badge - $4.99 (permanent)
- 🎨 Custom Themes - $1.99

## API Endpoints

### Subscription Management
- `POST /api/create-subscription-checkout` - Create subscription checkout
- `POST /api/cancel-subscription` - Cancel active subscription
- `GET /api/membership/:userId` - Get membership status

### One-Time Purchases
- `POST /api/create-purchase-checkout` - Create one-time purchase checkout

### Collaboration Limits
- `POST /api/use-collaboration-request` - Track collaboration request usage

### Webhooks
- `POST /api/webhook` - Handle Stripe webhook events

## Testing the System

### Test Premium Subscription
1. Log in to the app
2. Go to Membership tab
3. Click "Subscribe Monthly" or "Subscribe Yearly"
4. Use test card: `4242 4242 4242 4242`
5. Verify Premium status appears
6. Check collaboration limit is now unlimited

### Test One-Time Purchases
1. Go to Membership tab
2. Click "Buy Now" on any in-app purchase
3. Complete checkout with test card
4. Verify purchase appears in "Active Purchases"

### Test Collaboration Limits
1. As FREE user, try to send 4 collaboration requests
2. 4th request should prompt upgrade to Premium
3. As PREMIUM user, send unlimited requests

## Troubleshooting

### Subscription Not Activating
- Check webhook is configured correctly
- Verify `checkout.session.completed` event is enabled
- Check server logs for webhook errors

### Payment Failing
- Verify Stripe API keys are correct
- Check test mode vs. live mode
- Review Stripe Dashboard for errors

### User Not Found Error
- Ensure user is logged in before purchasing
- Check `appState.user.id` is populated

## Security Notes

- ✓ Never expose `STRIPE_SECRET_KEY` in frontend code
- ✓ Always validate webhook signatures in production
- ✓ Use HTTPS for webhook endpoints
- ✓ Store sensitive data server-side only
- ✓ Validate user permissions on all API calls

## Next Steps

1. Create Stripe products and get Price IDs
2. Update `.env` with all keys
3. Update `index.html` with actual Price IDs
4. Test thoroughly in test mode
5. Configure webhooks
6. Deploy to production
7. Switch to live keys
8. Monitor and iterate

## Support Resources

- [Stripe Documentation](https://stripe.com/docs)
- [Stripe Webhooks Guide](https://stripe.com/docs/webhooks)
- [Stripe Testing](https://stripe.com/docs/testing)
- [Stripe Dashboard](https://dashboard.stripe.com/)
