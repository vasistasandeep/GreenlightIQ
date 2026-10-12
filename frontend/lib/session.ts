/**
 * Client-side session handling for the CineROI AI frontend (R19).
 *
 * The backend issues a session credential at login (`POST /auth/login`) that the
 * typed API client forwards as an `Authorization: Bearer <token>` header on every
 * protected request (R19.2, R19.3). This module is the single source of truth for
 * that credential in the browser.
 *
 * Server Components cannot read this store (no `window`); they pass the token
 * explicitly to {@link apiFetch} via `RequestOptions.token`. Client Components rely
 * on the ambient token persisted here after login.
 */

const SESSION_STORAGE_KEY = "cineroi.session.token";

type SessionListener = (token: string | null) => void;

const listeners = new Set<SessionListener>();

/** True when running in a browser with access to `window`/`localStorage`. */
function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

/**
 * Read the current session token, or `null` when there is no active session.
 * Always `null` on the server — callers there must pass the token explicitly.
 */
export function getSessionToken(): string | null {
  if (!isBrowser()) {
    return null;
  }
  try {
    return window.localStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    // localStorage can throw in private-mode / restricted contexts.
    return null;
  }
}

/**
 * Persist a session token issued by the backend after a successful login (R19.2),
 * or clear it when `token` is `null`. Notifies subscribers of the change.
 */
export function setSessionToken(token: string | null): void {
  if (isBrowser()) {
    try {
      if (token) {
        window.localStorage.setItem(SESSION_STORAGE_KEY, token);
      } else {
        window.localStorage.removeItem(SESSION_STORAGE_KEY);
      }
    } catch {
      // Ignore storage failures; the in-memory listeners still fire.
    }
  }
  for (const listener of listeners) {
    listener(token);
  }
}

/** Drop the current session (logout / expiry). Convenience over `setSessionToken(null)`. */
export function clearSessionToken(): void {
  setSessionToken(null);
}

/**
 * Subscribe to session token changes (e.g. to redirect to login on expiry).
 * Returns an unsubscribe function.
 */
export function onSessionChange(listener: SessionListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
