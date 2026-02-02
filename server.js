import express from 'express';
import cors from 'cors';
import dotenv from 'dotenv';
import Stripe from 'stripe';
import bcrypt from 'bcryptjs';
import crypto from 'crypto';
import fs from 'fs/promises';
import path from 'path';
import session from 'express-session';
import passport from 'passport';
import { Strategy as GoogleStrategy } from 'passport-google-oauth20';
import { Strategy as FacebookStrategy } from 'passport-facebook';
import { Strategy as GitHubStrategy } from 'passport-github2';
import { Server as SocketIOServer } from 'socket.io';
import http from 'http';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

// Get __dirname equivalent in ES modules
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load environment variables
dotenv.config();

const app = express();
const httpServer = http.createServer(app);
const io = new SocketIOServer(httpServer, {
  cors: { origin: '*', credentials: true }
});
const port = process.env.PORT || 3000;
const domain = process.env.DOMAIN || `http://localhost:${port}`;
const stripeSecret = process.env.STRIPE_SECRET_KEY;
const usersFile = process.env.USERS_FILE || path.join(process.cwd(), 'users.json');
const messagesFile = path.join(process.cwd(), 'messages.json');

const stripe = stripeSecret ? new Stripe(stripeSecret) : null;

if (!stripe) {
  console.warn('⚠️ STRIPE_SECRET_KEY is missing. Stripe checkout will be disabled.');
}

// Middleware
app.use(cors({ origin: '*', credentials: true }));
app.use(express.json());
app.use(session({
  secret: process.env.SESSION_SECRET || 'music-connectz-secret-key-change-in-production',
  resave: false,
  saveUninitialized: false,
  cookie: { secure: false, maxAge: 24 * 60 * 60 * 1000 } // 24 hours
}));
app.use(passport.initialize());
app.use(passport.session());

// Passport serialization
passport.serializeUser((user, done) => done(null, user.id));
passport.deserializeUser(async (id, done) => {
  const users = await readUsers();
  const user = users.find(u => u.id === id);
  done(null, user);
});

// OAuth Strategies
if (process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET) {
  passport.use(new GoogleStrategy({
    clientID: process.env.GOOGLE_CLIENT_ID,
    clientSecret: process.env.GOOGLE_CLIENT_SECRET,
    callbackURL: `${domain}/api/auth/google/callback`
  }, async (accessToken, refreshToken, profile, done) => {
    try {
      const users = await readUsers();
      const email = normalizeEmail(profile.emails?.[0]?.value || '');
      let user = users.find(u => u.email === email || u.googleId === profile.id);
      
      if (!user) {
        user = {
          id: crypto.randomUUID(),
          email,
          username: profile.displayName || '',
          googleId: profile.id,
          createdAt: new Date().toISOString(),
          // Membership tier fields
          membershipTier: 'free',
          collaborationRequestsUsed: 0,
          collaborationRequestsLimit: 3,
          subscriptionId: null,
          subscriptionStatus: null,
          subscriptionExpiry: null,
          inAppPurchases: [],
          profileBoostExpiry: null,
          featuredArtistStatus: false,
          premiumBadge: false,
          customTheme: null
        };
        applyPremiumForBypass(user);
        users.push(user);
        await writeUsers(users);
      } else if (!user.googleId) {
        user.googleId = profile.id;
        await writeUsers(users);
      }
      
      done(null, user);
    } catch (error) {
      done(error, null);
    }
  }));
}

if (process.env.FACEBOOK_APP_ID && process.env.FACEBOOK_APP_SECRET) {
  passport.use(new FacebookStrategy({
    clientID: process.env.FACEBOOK_APP_ID,
    clientSecret: process.env.FACEBOOK_APP_SECRET,
    callbackURL: `${domain}/api/auth/facebook/callback`,
    profileFields: ['id', 'emails', 'name']
  }, async (accessToken, refreshToken, profile, done) => {
    try {
      const users = await readUsers();
      const email = normalizeEmail(profile.emails?.[0]?.value || '');
      let user = users.find(u => u.email === email || u.facebookId === profile.id);
      
      if (!user) {
        user = {
          id: crypto.randomUUID(),
          email,
          username: `${profile.name?.givenName || ''} ${profile.name?.familyName || ''}`.trim(),
          facebookId: profile.id,
          createdAt: new Date().toISOString(),
          // Membership tier fields
          membershipTier: 'free',
          collaborationRequestsUsed: 0,
          collaborationRequestsLimit: 3,
          subscriptionId: null,
          subscriptionStatus: null,
          subscriptionExpiry: null,
          inAppPurchases: [],
          profileBoostExpiry: null,
          featuredArtistStatus: false,
          premiumBadge: false,
          customTheme: null
        };
        applyPremiumForBypass(user);
        users.push(user);
        await writeUsers(users);
      } else if (!user.facebookId) {
        user.facebookId = profile.id;
        await writeUsers(users);
      }
      
      done(null, user);
    } catch (error) {
      done(error, null);
    }
  }));
}

if (process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET) {
  passport.use(new GitHubStrategy({
    clientID: process.env.GITHUB_CLIENT_ID,
    clientSecret: process.env.GITHUB_CLIENT_SECRET,
    callbackURL: `${domain}/api/auth/github/callback`
  }, async (accessToken, refreshToken, profile, done) => {
    try {
      const users = await readUsers();
      const email = normalizeEmail(profile.emails?.[0]?.value || '');
      let user = users.find(u => u.email === email || u.githubId === profile.id);
      
      if (!user) {
        user = {
          id: crypto.randomUUID(),
          email,
          username: profile.username || profile.displayName || '',
          githubId: profile.id,
          createdAt: new Date().toISOString(),
          // Membership tier fields
          membershipTier: 'free',
          collaborationRequestsUsed: 0,
          collaborationRequestsLimit: 3,
          subscriptionId: null,
          subscriptionStatus: null,
          subscriptionExpiry: null,
          inAppPurchases: [],
          profileBoostExpiry: null,
          featuredArtistStatus: false,
          premiumBadge: false,
          customTheme: null
        };
        applyPremiumForBypass(user);
        users.push(user);
        await writeUsers(users);
      } else if (!user.githubId) {
        user.githubId = profile.id;
        await writeUsers(users);
      }
      
      done(null, user);
    } catch (error) {
      done(error, null);
    }
  }));
}

const readUsers = async () => {
  try {
    const raw = await fs.readFile(usersFile, 'utf8');
    const users = JSON.parse(raw);
    return Array.isArray(users) ? users : [];
  } catch (error) {
    if (error.code === 'ENOENT') {
      return [];
    }
    throw error;
  }
};

const writeUsers = async (users) => {
  await fs.writeFile(usersFile, JSON.stringify(users, null, 2), 'utf8');
};

const readMessages = async () => {
  try {
    const raw = await fs.readFile(messagesFile, 'utf8');
    const messages = JSON.parse(raw);
    return Array.isArray(messages) ? messages : [];
  } catch (error) {
    if (error.code === 'ENOENT') {
      return [];
    }
    throw error;
  }
};

const writeMessages = async (messages) => {
  await fs.writeFile(messagesFile, JSON.stringify(messages, null, 2), 'utf8');
};

const normalizeEmail = (email) => String(email || '').trim().toLowerCase();

const premiumBypassEmails = [normalizeEmail('ctkoth@gmail.com')];
const isBypassEmail = (email) => premiumBypassEmails.includes(normalizeEmail(email));
const isPremiumUser = (user) => !!user && (user.membershipTier === 'premium' || isBypassEmail(user.email));
const applyPremiumForBypass = (user) => {
  if (!user || !isBypassEmail(user.email)) return;
  user.membershipTier = 'premium';
  user.subscriptionStatus = 'active';
  user.collaborationRequestsLimit = 999999;
  user.featuredArtistStatus = true;
};

// Socket.io message handling
io.on('connection', (socket) => {
  console.log(`User connected: ${socket.id}`);

  // Send all messages to new user
  socket.on('get-messages', async (callback) => {
    const messages = await readMessages();
    callback(messages);
  });

  // Handle new message
  socket.on('send-message', async (data, callback) => {
    try {
      const { userId, username, message, conversationWith, file } = data;
      
      if (!userId || !message || !conversationWith) {
        return callback({ error: 'Missing required fields' });
      }

      const users = await readUsers();
      const sender = users.find(u => u.id === userId);
      if (!sender) {
        return callback({ error: 'User not found' });
      }
      if (!isPremiumUser(sender)) {
        return callback({ error: 'Premium required for direct messaging' });
      }

      const messages = await readMessages();
      const newMessage = {
        id: crypto.randomUUID(),
        senderId: userId,
        senderName: username,
        recipientId: conversationWith,
        text: message,
        timestamp: new Date().toISOString(),
        read: false,
        file: file ? {
          name: file.name,
          size: file.size,
          type: file.type,
          // Store file data as base64 string if provided
          data: file.data ? (typeof file.data === 'string' ? file.data : Buffer.from(file.data).toString('base64')) : null
        } : null
      };

      messages.push(newMessage);
      await writeMessages(messages);

      // Emit to all users (file data included)
      io.emit('new-message', newMessage);
      callback({ ok: true, message: newMessage });
    } catch (error) {
      console.error('Message error:', error);
      callback({ error: error.message });
    }
  });

  // Edit message (within 15 minutes)
  socket.on('edit-message', async (data, callback) => {
    try {
      const { messageId, conversationWith, newText } = data;
      const messages = await readMessages();
      const msg = messages.find(m => m.id === messageId);
      
      if (!msg) {
        return callback({ error: 'Message not found' });
      }
      
      // Check if user is sender
      if (msg.senderId !== socket.handshake.auth.userId) {
        return callback({ error: 'Not authorized to edit this message' });
      }
      
      // Check if within 15 minutes
      const timePassed = (Date.now() - new Date(msg.timestamp).getTime()) / 1000 / 60;
      if (timePassed > 15) {
        return callback({ error: 'Cannot edit message after 15 minutes' });
      }
      
      msg.text = newText;
      msg.editedAt = new Date().toISOString();
      await writeMessages(messages);
      
      // Broadcast edit to both users
      io.emit('message-edited', {
        messageId,
        newText,
        editedAt: msg.editedAt,
        senderId: msg.senderId,
        conversationWith
      });
      callback({ ok: true });
    } catch (error) {
      console.error('Edit message error:', error);
      callback({ error: error.message });
    }
  });

  // Delete message (within 15 minutes)
  socket.on('delete-message', async (data, callback) => {
    try {
      const { messageId, conversationWith } = data;
      const messages = await readMessages();
      const msgIdx = messages.findIndex(m => m.id === messageId);
      
      if (msgIdx === -1) {
        return callback({ error: 'Message not found' });
      }
      
      const msg = messages[msgIdx];
      
      // Check if user is sender
      if (msg.senderId !== socket.handshake.auth.userId) {
        return callback({ error: 'Not authorized to delete this message' });
      }
      
      // Check if within 15 minutes
      const timePassed = (Date.now() - new Date(msg.timestamp).getTime()) / 1000 / 60;
      if (timePassed > 15) {
        return callback({ error: 'Cannot delete message after 15 minutes' });
      }
      
      messages.splice(msgIdx, 1);
      await writeMessages(messages);
      
      // Broadcast deletion to both users
      io.emit('message-deleted', {
        messageId,
        senderId: msg.senderId,
        conversationWith
      });
      callback({ ok: true });
    } catch (error) {
      console.error('Delete message error:', error);
      callback({ error: error.message });
    }
  });

  // Mark message as read
  socket.on('mark-read', async (data, callback) => {
    try {
      const { messageId } = data;
      const messages = await readMessages();
      const msg = messages.find(m => m.id === messageId);
      
      if (msg) {
        msg.read = true;
        await writeMessages(messages);
        io.emit('message-read', messageId);
      }
      callback({ ok: true });
    } catch (error) {
      callback({ error: error.message });
    }
  });

  socket.on('disconnect', () => {
    console.log(`User disconnected: ${socket.id}`);
  });
});

// Health check
app.get('/api/health', (req, res) => {
  res.json({ ok: true, status: 'healthy', time: new Date().toISOString() });
});



// Login with password
app.post('/api/login', async (req, res) => {
  try {
    const { email, password } = req.body || {};
    const normalizedEmail = normalizeEmail(email);

    if (!normalizedEmail || !password) {
      return res.status(400).json({ error: 'Email and password required' });
    }

    const users = await readUsers();
    const user = users.find((u) => u.email === normalizedEmail);
    if (!user) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const isValid = await bcrypt.compare(String(password), user.passwordHash);
    if (!isValid) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    applyPremiumForBypass(user);
    res.json({ ok: true, user: { id: user.id, email: user.email, username: user.username, membershipTier: isPremiumUser(user) ? 'premium' : (user.membershipTier || 'free'), featuredArtistStatus: !!user.featuredArtistStatus, premiumBadge: !!user.premiumBadge, profileBoostExpiry: user.profileBoostExpiry || null, customTheme: user.customTheme || null } });
  } catch (error) {
    console.error('Login error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Login with phone number
app.post('/api/login-phone', async (req, res) => {
  try {
    const { phone, password } = req.body || {};
    const normalizedPhone = String(phone || '').trim();

    if (!normalizedPhone || !password) {
      return res.status(400).json({ error: 'Phone and password required' });
    }

    const users = await readUsers();
    const user = users.find((u) => u.phone === normalizedPhone);
    if (!user) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    const isValid = await bcrypt.compare(String(password), user.passwordHash);
    if (!isValid) {
      return res.status(401).json({ error: 'Invalid credentials' });
    }

    applyPremiumForBypass(user);
    res.json({ ok: true, user: { id: user.id, email: user.email, username: user.username, phone: user.phone, membershipTier: isPremiumUser(user) ? 'premium' : (user.membershipTier || 'free'), featuredArtistStatus: !!user.featuredArtistStatus, premiumBadge: !!user.premiumBadge, profileBoostExpiry: user.profileBoostExpiry || null, customTheme: user.customTheme || null } });
  } catch (error) {
    console.error('Phone login error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Request password reset
app.post('/api/forgot-password', async (req, res) => {
  try {
    const { email } = req.body || {};
    const normalizedEmail = normalizeEmail(email);

    if (!normalizedEmail) {
      return res.status(400).json({ error: 'Email required' });
    }

    const users = await readUsers();
    const user = users.find((u) => u.email === normalizedEmail);
    
    // Always return success for security (don't reveal if email exists)
    if (!user) {
      return res.json({ ok: true, message: 'If account exists, reset code sent' });
    }

    // Generate 6-digit reset code
    const resetCode = Math.floor(100000 + Math.random() * 900000).toString();
    const resetExpiry = Date.now() + 15 * 60 * 1000; // 15 minutes

    user.resetCode = resetCode;
    user.resetExpiry = resetExpiry;
    await writeUsers(users);

    // In production, send this via email. For now, log it
    console.log(`Password reset code for ${normalizedEmail}: ${resetCode}`);

    res.json({ ok: true, message: 'If account exists, reset code sent', resetCode });
  } catch (error) {
    console.error('Forgot password error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Reset password with code
app.post('/api/reset-password', async (req, res) => {
  try {
    const { email, code, newPassword } = req.body || {};
    const normalizedEmail = normalizeEmail(email);

    if (!normalizedEmail || !code || !newPassword) {
      return res.status(400).json({ error: 'Email, code, and new password required' });
    }

    if (String(newPassword).length < 8) {
      return res.status(400).json({ error: 'Password must be at least 8 characters' });
    }

    const users = await readUsers();
    const user = users.find((u) => u.email === normalizedEmail);
    
    if (!user || !user.resetCode || !user.resetExpiry) {
      return res.status(400).json({ error: 'Invalid or expired reset code' });
    }

    if (Date.now() > user.resetExpiry) {
      return res.status(400).json({ error: 'Reset code expired' });
    }

    if (user.resetCode !== String(code)) {
      return res.status(400).json({ error: 'Invalid reset code' });
    }

    // Update password and clear reset fields
    user.passwordHash = await bcrypt.hash(String(newPassword), 12);
    delete user.resetCode;
    delete user.resetExpiry;
    await writeUsers(users);

    res.json({ ok: true, message: 'Password reset successful' });
  } catch (error) {
    console.error('Reset password error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Update register to include phone
app.post('/api/register', async (req, res) => {
  try {
    const { email, password, username, phone } = req.body || {};
    const normalizedEmail = normalizeEmail(email);

    if (!normalizedEmail) {
      return res.status(400).json({ error: 'Email required' });
    }
    if (!password || String(password).length < 8) {
      return res.status(400).json({ error: 'Password must be at least 8 characters' });
    }

    const users = await readUsers();
    const existing = users.find((user) => user.email === normalizedEmail);
    if (existing) {
      return res.status(409).json({ error: 'Email already registered' });
    }

    const passwordHash = await bcrypt.hash(String(password), 12);
    const newUser = {
      id: crypto.randomUUID(),
      email: normalizedEmail,
      username: username ? String(username).trim() : '',
      phone: phone ? String(phone).trim() : '',
      passwordHash,
      createdAt: new Date().toISOString(),
      // Membership tier fields
      membershipTier: 'free', // 'free' or 'premium'
      collaborationRequestsUsed: 0,
      collaborationRequestsLimit: 3, // Free tier limit
      subscriptionId: null,
      subscriptionStatus: null,
      subscriptionExpiry: null,
      inAppPurchases: [], // Array of purchased items
      profileBoostExpiry: null,
      featuredArtistStatus: false,
      premiumBadge: false,
      customTheme: null
    };

    applyPremiumForBypass(newUser);
    users.push(newUser);
    await writeUsers(users);

    res.status(201).json({ ok: true, user: { id: newUser.id, email: newUser.email, username: newUser.username, phone: newUser.phone, membershipTier: isPremiumUser(newUser) ? 'premium' : (newUser.membershipTier || 'free'), featuredArtistStatus: !!newUser.featuredArtistStatus, premiumBadge: !!newUser.premiumBadge, profileBoostExpiry: newUser.profileBoostExpiry || null, customTheme: newUser.customTheme || null } });
  } catch (error) {
    console.error('Register error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Remove duplicate register endpoint below

// Get all messages for a user
app.get('/api/messages/:userId', async (req, res) => {
  try {
    const { userId } = req.params;
    const messages = await readMessages();
    const userMessages = messages.filter(m => 
      m.senderId === userId || m.recipientId === userId
    );
    res.json(userMessages);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Get conversation between two users
app.get('/api/messages/:userId/:otherUserId', async (req, res) => {
  try {
    const { userId, otherUserId } = req.params;
    const messages = await readMessages();
    const conversation = messages.filter(m => 
      (m.senderId === userId && m.recipientId === otherUserId) ||
      (m.senderId === otherUserId && m.recipientId === userId)
    ).sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    res.json(conversation);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Create checkout session
app.post('/api/create-checkout', async (req, res) => {
  if (!stripe) {
    return res.status(503).json({ error: 'Stripe is not configured' });
  }

  try {
    const { amount, description, taxMode, customerEmail } = req.body || {};

    if (!amount || Number(amount) <= 0) {
      return res.status(400).json({ error: 'Invalid amount' });
    }
    if (!description) {
      return res.status(400).json({ error: 'Description required' });
    }

    const sessionConfig = {
      line_items: [
        {
          price_data: {
            currency: 'usd',
            product_data: { name: description },
            unit_amount: Math.round(Number(amount) * 100),
          },
          quantity: 1,
        },
      ],
      mode: 'payment',
      success_url: `${domain}/success?session_id={CHECKOUT_SESSION_ID}`,
      cancel_url: `${domain}/cancel`,
    };

    if (taxMode === 'automatic') {
      sessionConfig.automatic_tax = { enabled: true };
      sessionConfig.customer_update = { address: 'auto' };
    }

    if (customerEmail) {
      sessionConfig.customer_email = customerEmail;
    }

    const session = await stripe.checkout.sessions.create(sessionConfig);

    res.json({ url: session.url, sessionId: session.id, message: 'Checkout session created' });
  } catch (error) {
    console.error('Stripe error:', error);
    res.status(500).json({ error: error.message || 'Internal server error' });
  }
});

// Create subscription checkout for Premium tier
app.post('/api/create-subscription-checkout', async (req, res) => {
  if (!stripe) {
    return res.status(503).json({ error: 'Stripe is not configured' });
  }

  try {
    const { userId, priceId, billingPeriod } = req.body || {};

    if (!userId || !priceId) {
      return res.status(400).json({ error: 'User ID and price ID required' });
    }

    const users = await readUsers();
    const user = users.find(u => u.id === userId);
    
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }

    // Create or retrieve Stripe customer
    let customerId = user.stripeCustomerId;
    if (!customerId) {
      const customer = await stripe.customers.create({
        email: user.email,
        metadata: { userId: user.id }
      });
      customerId = customer.id;
      user.stripeCustomerId = customerId;
      await writeUsers(users);
    }

    const session = await stripe.checkout.sessions.create({
      customer: customerId,
      line_items: [{ price: priceId, quantity: 1 }],
      mode: 'subscription',
      success_url: `${domain}/?subscription=success`,
      cancel_url: `${domain}/?subscription=cancel`,
      metadata: {
        userId: user.id,
        billingPeriod: billingPeriod || 'monthly'
      }
    });

    res.json({ url: session.url, sessionId: session.id });
  } catch (error) {
    console.error('Subscription error:', error);
    res.status(500).json({ error: error.message || 'Internal server error' });
  }
});

// Create one-time purchase checkout (in-app purchases)
app.post('/api/create-purchase-checkout', async (req, res) => {
  if (!stripe) {
    return res.status(503).json({ error: 'Stripe is not configured' });
  }

  try {
    const { userId, purchaseType, amount, description } = req.body || {};

    if (!userId || !purchaseType || !amount) {
      return res.status(400).json({ error: 'Missing required fields' });
    }

    const users = await readUsers();
    const user = users.find(u => u.id === userId);
    
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }

    const session = await stripe.checkout.sessions.create({
      customer_email: user.email,
      line_items: [{
        price_data: {
          currency: 'usd',
          product_data: { name: description || purchaseType },
          unit_amount: Math.round(Number(amount) * 100),
        },
        quantity: 1,
      }],
      mode: 'payment',
      success_url: `${domain}/?purchase=success&type=${purchaseType}`,
      cancel_url: `${domain}/?purchase=cancel`,
      metadata: {
        userId: user.id,
        purchaseType: purchaseType
      }
    });

    res.json({ url: session.url, sessionId: session.id });
  } catch (error) {
    console.error('Purchase error:', error);
    res.status(500).json({ error: error.message || 'Internal server error' });
  }
});

// Stripe webhook handler
app.post('/api/webhook', express.raw({ type: 'application/json' }), async (req, res) => {
  if (!stripe) {
    return res.status(503).send('Stripe not configured');
  }

  const sig = req.headers['stripe-signature'];
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET;

  let event;

  try {
    if (webhookSecret) {
      event = stripe.webhooks.constructEvent(req.body, sig, webhookSecret);
    } else {
      event = JSON.parse(req.body.toString());
    }
  } catch (err) {
    console.error('Webhook signature verification failed:', err.message);
    return res.status(400).send(`Webhook Error: ${err.message}`);
  }

  try {
    const users = await readUsers();

    switch (event.type) {
      case 'checkout.session.completed':
        const session = event.data.object;
        const userId = session.metadata?.userId;
        
        if (!userId) break;

        const user = users.find(u => u.id === userId);
        if (!user) break;

        // Handle subscription
        if (session.mode === 'subscription') {
          user.membershipTier = 'premium';
          user.subscriptionId = session.subscription;
          user.subscriptionStatus = 'active';
          user.collaborationRequestsLimit = 999999; // Unlimited
          user.featuredArtistStatus = true;
        }
        
        // Handle one-time purchase
        if (session.mode === 'payment' && session.metadata?.purchaseType) {
          const purchaseType = session.metadata.purchaseType;
          const purchase = {
            id: crypto.randomUUID(),
            type: purchaseType,
            purchaseDate: new Date().toISOString(),
            amount: session.amount_total / 100
          };
          
          if (!user.inAppPurchases) user.inAppPurchases = [];
          user.inAppPurchases.push(purchase);

          // Apply purchase benefits
          if (purchaseType === 'profile-boost') {
            user.profileBoostExpiry = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
          } else if (purchaseType === 'collab-unlock') {
            const currentLimit = Number.isFinite(user.collaborationRequestsLimit) ? user.collaborationRequestsLimit : 3;
            user.collaborationRequestsLimit = currentLimit + 1;
          } else if (purchaseType === 'premium-badge') {
            user.premiumBadge = true;
          } else if (purchaseType === 'custom-theme') {
            user.customTheme = 'premium';
          }
        }

        await writeUsers(users);
        break;

      case 'customer.subscription.updated':
      case 'customer.subscription.deleted':
        const subscription = event.data.object;
        const subUser = users.find(u => u.subscriptionId === subscription.id);
        
        if (subUser) {
          if (subscription.status === 'active') {
            subUser.membershipTier = 'premium';
            subUser.subscriptionStatus = 'active';
            subUser.collaborationRequestsLimit = 999999;
            subUser.featuredArtistStatus = true;
          } else {
            subUser.membershipTier = 'free';
            subUser.subscriptionStatus = subscription.status;
            subUser.collaborationRequestsLimit = 3;
            subUser.featuredArtistStatus = false;
          }
          await writeUsers(users);
        }
        break;
    }

    res.json({ received: true });
  } catch (error) {
    console.error('Webhook handler error:', error);
    res.status(500).json({ error: 'Webhook handler failed' });
  }
});

// Get user membership details
app.get('/api/membership/:userId', async (req, res) => {
  try {
    const { userId } = req.params;
    const users = await readUsers();
    const user = users.find(u => u.id === userId);
    
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }

    applyPremiumForBypass(user);
    const membershipData = {
      tier: isPremiumUser(user) ? 'premium' : (user.membershipTier || 'free'),
      collaborationRequestsUsed: user.collaborationRequestsUsed || 0,
      collaborationRequestsLimit: isPremiumUser(user) ? 999999 : (user.collaborationRequestsLimit || 3),
      subscriptionStatus: isPremiumUser(user) ? 'active' : (user.subscriptionStatus || null),
      subscriptionExpiry: user.subscriptionExpiry || null,
      inAppPurchases: user.inAppPurchases || [],
      profileBoostExpiry: user.profileBoostExpiry || null,
      featuredArtistStatus: isPremiumUser(user) ? true : (user.featuredArtistStatus || false),
      premiumBadge: user.premiumBadge || false,
      customTheme: user.customTheme || null
    };

    res.json(membershipData);
  } catch (error) {
    console.error('Get membership error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Cancel subscription
app.post('/api/cancel-subscription', async (req, res) => {
  if (!stripe) {
    return res.status(503).json({ error: 'Stripe is not configured' });
  }

  try {
    const { userId } = req.body || {};
    
    if (!userId) {
      return res.status(400).json({ error: 'User ID required' });
    }

    const users = await readUsers();
    const user = users.find(u => u.id === userId);
    
    if (!user || !user.subscriptionId) {
      return res.status(404).json({ error: 'No active subscription found' });
    }

    await stripe.subscriptions.cancel(user.subscriptionId);

    user.membershipTier = 'free';
    user.subscriptionStatus = 'canceled';
    user.collaborationRequestsLimit = 3;
    user.featuredArtistStatus = false;
    
    await writeUsers(users);

    res.json({ ok: true, message: 'Subscription canceled' });
  } catch (error) {
    console.error('Cancel subscription error:', error);
    res.status(500).json({ error: error.message || 'Internal server error' });
  }
});

// Increment collaboration request count
app.post('/api/use-collaboration-request', async (req, res) => {
  try {
    const { userId } = req.body || {};
    
    if (!userId) {
      return res.status(400).json({ error: 'User ID required' });
    }

    const users = await readUsers();
    const user = users.find(u => u.id === userId);
    
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }

    // Check if user has exceeded limit
    const usedRequests = user.collaborationRequestsUsed || 0;
    const limit = isPremiumUser(user) ? 999999 : (user.collaborationRequestsLimit || 3);

    if (usedRequests >= limit && !isPremiumUser(user)) {
      return res.status(403).json({ 
        error: 'Collaboration request limit reached',
        upgrade: true,
        message: 'Upgrade to Premium for unlimited collaboration requests'
      });
    }

    user.collaborationRequestsUsed = usedRequests + 1;
    await writeUsers(users);

    res.json({ 
      ok: true, 
      used: user.collaborationRequestsUsed,
      limit: limit,
      remaining: limit - user.collaborationRequestsUsed
    });
  } catch (error) {
    console.error('Use collaboration request error:', error);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// Basic success/cancel placeholders
app.get('/success', (req, res) => {
  res.send('<h2>Payment successful 🎉</h2>');
});

app.get('/cancel', (req, res) => {
  res.send('<h2>Payment canceled. Try again.</h2>');
});

// OAuth Routes
app.get('/api/auth/google/available', (req, res) => {
  const enabled = !!(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
  res.json({ enabled });
});

app.get('/api/auth/google', (req, res, next) => {
  if (!process.env.GOOGLE_CLIENT_ID || !process.env.GOOGLE_CLIENT_SECRET) {
    return res.status(501).json({ error: 'Google login is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.' });
  }
  return passport.authenticate('google', { scope: ['profile', 'email'] })(req, res, next);
});

app.get('/api/auth/google/callback', (req, res, next) => {
  if (!process.env.GOOGLE_CLIENT_ID || !process.env.GOOGLE_CLIENT_SECRET) {
    return res.status(501).send('Google login is not configured.');
  }
  return passport.authenticate('google', { failureRedirect: '/login' })(req, res, next);
},
  (req, res) => {
    // Successful authentication
    const userData = {
      id: req.user.id,
      email: req.user.email,
      username: req.user.username
    };
    res.redirect(`http://localhost:8000?social_login=success&user=${encodeURIComponent(JSON.stringify(userData))}`);
  }
);

app.get('/api/auth/facebook', (req, res, next) => {
  if (!process.env.FACEBOOK_APP_ID || !process.env.FACEBOOK_APP_SECRET) {
    return res.status(501).json({ error: 'Facebook login is not configured. Set FACEBOOK_APP_ID and FACEBOOK_APP_SECRET.' });
  }
  return passport.authenticate('facebook', { scope: ['email'] })(req, res, next);
});

app.get('/api/auth/facebook/callback', (req, res, next) => {
  if (!process.env.FACEBOOK_APP_ID || !process.env.FACEBOOK_APP_SECRET) {
    return res.status(501).send('Facebook login is not configured.');
  }
  return passport.authenticate('facebook', { failureRedirect: '/login' })(req, res, next);
},
  (req, res) => {
    const userData = {
      id: req.user.id,
      email: req.user.email,
      username: req.user.username
    };
    res.redirect(`http://localhost:8000?social_login=success&user=${encodeURIComponent(JSON.stringify(userData))}`);
  }
);

app.get('/api/auth/github', (req, res, next) => {
  if (!process.env.GITHUB_CLIENT_ID || !process.env.GITHUB_CLIENT_SECRET) {
    return res.status(501).json({ error: 'GitHub login is not configured. Set GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.' });
  }
  return passport.authenticate('github', { scope: ['user:email'] })(req, res, next);
});

app.get('/api/auth/github/callback', (req, res, next) => {
  if (!process.env.GITHUB_CLIENT_ID || !process.env.GITHUB_CLIENT_SECRET) {
    return res.status(501).send('GitHub login is not configured.');
  }
  return passport.authenticate('github', { failureRedirect: '/login' })(req, res, next);
},
  (req, res) => {
    const userData = {
      id: req.user.id,
      email: req.user.email,
      username: req.user.username
    };
    res.redirect(`http://localhost:8000?social_login=success&user=${encodeURIComponent(JSON.stringify(userData))}`);
  }
);

// Serve static files and index.html
app.use(express.static('.'));

app.get('/', (req, res) => {
  res.sendFile(__dirname + '/index.html');
});

// Catch-all route for client-side routing
app.get('*', (req, res) => {
  res.sendFile(__dirname + '/index.html');
});

httpServer.listen(port, () => {
  console.log(`✅ Server running at ${domain}`);
});
