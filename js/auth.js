/**
 * Auth Module
 * Silent auto-login via Supabase Auth REST API (no SDK).
 * Credentials are stored in config.js and a session is cached in localStorage.
 */

import { SUPABASE_URL, SUPABASE_KEY, AUTH_EMAIL, AUTH_PASSWORD } from './config.js';

const SESSION_KEY = 'nb_session';

function getStoredSession() {
    try {
        const raw = localStorage.getItem(SESSION_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function storeSession(session) {
    const expires_at = Date.now() + session.expires_in * 1000;
    localStorage.setItem(SESSION_KEY, JSON.stringify({
        access_token: session.access_token,
        refresh_token: session.refresh_token,
        expires_at,
        user: session.user
    }));
}

function clearSession() {
    localStorage.removeItem(SESSION_KEY);
}

async function signIn() {
    const response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
        method: 'POST',
        headers: {
            'apikey': SUPABASE_KEY,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ email: AUTH_EMAIL, password: AUTH_PASSWORD })
    });

    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error_description || err.message || 'Sign in failed');
    }

    const session = await response.json();
    storeSession(session);
    return session;
}

async function refreshSession(refreshToken) {
    const response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=refresh_token`, {
        method: 'POST',
        headers: {
            'apikey': SUPABASE_KEY,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ refresh_token: refreshToken })
    });

    if (!response.ok) throw new Error('Token refresh failed');

    const session = await response.json();
    storeSession(session);
    return session;
}

/**
 * Ensures a valid authenticated session exists.
 * 1. Uses cached session if still valid (60s buffer before expiry)
 * 2. Refreshes using refresh_token if expired
 * 3. Signs in fresh with stored credentials as last resort
 * @returns {{ access_token: string, user: object }}
 */
export async function ensureAuthenticated() {
    const stored = getStoredSession();

    // Valid session — not expired (with 60s buffer)
    if (stored && stored.expires_at > Date.now() + 60000) {
        return { access_token: stored.access_token, user: stored.user };
    }

    // Expired but have refresh token — try to refresh
    if (stored?.refresh_token) {
        try {
            const session = await refreshSession(stored.refresh_token);
            return { access_token: session.access_token, user: session.user };
        } catch {
            clearSession();
        }
    }

    // No session or refresh failed — sign in fresh
    const session = await signIn();
    return { access_token: session.access_token, user: session.user };
}
