/**
 * User Auth Module
 * Front-end user gate: load users, validate PIN, create user, manage current user.
 * The Supabase service-account JWT (state.accessToken) handles all DB calls.
 * Per-person tracking is purely a front-end concept stored in localStorage.
 */

import { SUPABASE_URL, SUPABASE_KEY } from './config.js';
import { state } from './state.js';

const LS_KEY = 'nb_current_user';

// ---------------------------------------------------------------------------
// LocalStorage helpers
// ---------------------------------------------------------------------------

export function getCurrentUser() {
    return localStorage.getItem(LS_KEY) || null;
}

export function setCurrentUser(name) {
    localStorage.setItem(LS_KEY, name);
    state.currentUser = name;
}

export function clearCurrentUser() {
    localStorage.removeItem(LS_KEY);
    state.currentUser = null;
}

// ---------------------------------------------------------------------------
// Supabase REST helpers
// ---------------------------------------------------------------------------

function authHeaders() {
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': `Bearer ${state.accessToken}`,
        'Content-Type': 'application/json'
    };
}

/**
 * Load all user names from app_users, sorted alphabetically.
 * @returns {Promise<string[]>}
 */
export async function loadUsers() {
    const response = await fetch(
        `${SUPABASE_URL}/rest/v1/app_users?select=name&order=name`,
        { headers: authHeaders() }
    );
    if (!response.ok) throw new Error('Failed to load users');
    const rows = await response.json();
    return rows.map(r => r.name);
}

/**
 * Check that the given name + PIN match a row in app_users.
 * @param {string} name
 * @param {string} pin
 * @returns {Promise<boolean>}
 */
export async function validatePin(name, pin) {
    const response = await fetch(
        `${SUPABASE_URL}/rest/v1/app_users?name=eq.${encodeURIComponent(name)}&pin=eq.${encodeURIComponent(pin)}&select=id`,
        { headers: authHeaders() }
    );
    if (!response.ok) return false;
    const rows = await response.json();
    return rows.length > 0;
}

/**
 * Create a new user in app_users.
 * @param {string} name
 * @param {string} pin
 * @returns {Promise<{success: boolean, error: string|null}>}
 */
export async function createUser(name, pin) {
    const response = await fetch(
        `${SUPABASE_URL}/rest/v1/app_users`,
        {
            method: 'POST',
            headers: {
                ...authHeaders(),
                'Prefer': 'return=minimal'
            },
            body: JSON.stringify({ name, pin })
        }
    );

    if (response.ok) return { success: true, error: null };

    let errorMsg = 'Could not create user';
    try {
        const err = await response.json();
        if (err.message && err.message.includes('unique')) {
            errorMsg = 'That name is already taken';
        } else if (err.message) {
            errorMsg = err.message;
        }
    } catch { /* ignore */ }

    return { success: false, error: errorMsg };
}

// ---------------------------------------------------------------------------
// Login overlay
// ---------------------------------------------------------------------------

/**
 * Show the "Who's scanning?" login overlay and return a Promise that
 * resolves with the chosen user name once they successfully sign in.
 * Resolves immediately if the user is already stored in localStorage.
 */
export async function showUserLoginOverlay() {
    const overlay = document.getElementById('userLoginOverlay');
    if (!overlay) return; // fallback: no overlay in DOM

    // Load users and build the name buttons
    let names = [];
    try {
        names = await loadUsers();
    } catch {
        names = [];
    }

    _renderNameButtons(names);

    overlay.style.display = 'flex';

    return new Promise(resolve => {
        // The three views share state through closures
        let pendingName = '';

        const selectView = document.getElementById('userSelectView');
        const pinView    = document.getElementById('userPinView');
        const addView    = document.getElementById('userAddView');

        // ---- helpers ----
        function showView(view) {
            [selectView, pinView, addView].forEach(v => v.style.display = 'none');
            view.style.display = 'block';
        }

        function signIn(name) {
            setCurrentUser(name);
            overlay.style.display = 'none';
            resolve(name);
        }

        // ---- select view: name buttons ----
        overlay.querySelectorAll('.user-name-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                pendingName = btn.dataset.name;
                document.getElementById('selectedUserName').textContent = pendingName;
                document.getElementById('pinInput').value = '';
                document.getElementById('pinError').textContent = '';
                showView(pinView);
                document.getElementById('pinInput').focus();
            });
        });

        // ---- select view: add user button ----
        document.getElementById('showAddUserBtn').addEventListener('click', () => {
            document.getElementById('newUserName').value = '';
            document.getElementById('newUserPin').value = '1234';
            document.getElementById('addUserError').textContent = '';
            showView(addView);
            document.getElementById('newUserName').focus();
        });

        // ---- pin view: back ----
        document.getElementById('pinBackBtn').addEventListener('click', () => {
            showView(selectView);
        });

        // ---- pin view: unlock ----
        async function attemptPin() {
            const pin = document.getElementById('pinInput').value.trim();
            if (!pin) return;

            const ok = await validatePin(pendingName, pin);
            if (ok) {
                signIn(pendingName);
            } else {
                document.getElementById('pinError').textContent = 'Wrong PIN, try again';
                document.getElementById('pinInput').value = '';
                document.getElementById('pinInput').focus();
            }
        }

        document.getElementById('unlockBtn').addEventListener('click', attemptPin);
        document.getElementById('pinInput').addEventListener('keydown', e => {
            if (e.key === 'Enter') attemptPin();
        });

        // ---- add view: back ----
        document.getElementById('addBackBtn').addEventListener('click', () => {
            showView(selectView);
        });

        // ---- add view: create & sign in ----
        async function attemptCreate() {
            const name = document.getElementById('newUserName').value.trim();
            const pin  = document.getElementById('newUserPin').value.trim();

            if (!name) {
                document.getElementById('addUserError').textContent = 'Please enter a name';
                return;
            }
            if (!pin) {
                document.getElementById('addUserError').textContent = 'Please enter a PIN';
                return;
            }

            document.getElementById('createUserBtn').disabled = true;
            const result = await createUser(name, pin);
            document.getElementById('createUserBtn').disabled = false;

            if (result.success) {
                signIn(name);
            } else {
                document.getElementById('addUserError').textContent = result.error;
            }
        }

        document.getElementById('createUserBtn').addEventListener('click', attemptCreate);
        document.getElementById('newUserName').addEventListener('keydown', e => {
            if (e.key === 'Enter') document.getElementById('newUserPin').focus();
        });
        document.getElementById('newUserPin').addEventListener('keydown', e => {
            if (e.key === 'Enter') attemptCreate();
        });
    });
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function _renderNameButtons(names) {
    const container = document.getElementById('userNameButtons');
    if (!container) return;
    container.innerHTML = '';
    names.forEach(name => {
        const btn = document.createElement('button');
        btn.className = 'user-name-btn';
        btn.dataset.name = name;
        btn.textContent = name;
        container.appendChild(btn);
    });
}
