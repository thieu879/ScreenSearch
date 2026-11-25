/**
 * Authentication API client — the real backend, not mock.
 *
 * All requests include `credentials: 'include'` so cookies travel with them.
 * The `fetchWithAuth` wrapper auto-refreshes on 401 and retries the original request once.
 *
 * CSRF: state-changing requests read the `csrf_token` cookie and send it as the
 * `X-CSRF-Token` header (double-submit cookie pattern).
 */

import { API_BASE } from './client';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface UserProfile {
  user_id: string;
  email: string;
  username: string | null;
  full_name: string | null;
  avatar: string | null;
  role: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  message: string;
  user: UserProfile;
}

export interface MessageResponse {
  message: string;
}

// ---------------------------------------------------------------------------
// CSRF helper
// ---------------------------------------------------------------------------

function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : '';
}

// ---------------------------------------------------------------------------
// Refresh lock — prevents multiple concurrent refresh attempts
// ---------------------------------------------------------------------------

let refreshPromise: Promise<boolean> | null = null;

async function doRefresh(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: 'POST',
      credentials: 'include',
    });
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Attempt to refresh the access token.  If a refresh is already in flight,
 * piggyback on it — this prevents a storm of 401 → refresh requests when
 * multiple API calls fail at the same time.
 */
async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;
  refreshPromise = doRefresh().finally(() => { refreshPromise = null; });
  return refreshPromise;
}

// ---------------------------------------------------------------------------
// fetchWithAuth — central fetch wrapper with auto-refresh
// ---------------------------------------------------------------------------

/**
 * fetch() with:
 *  - `credentials: 'include'` for cookies
 *  - CSRF header for mutating methods
 *  - Automatic 401 → refresh → retry (once)
 */
export async function fetchWithAuth(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  const method = (options.method ?? 'GET').toUpperCase();

  const headers = new Headers(options.headers);
  if (!headers.has('Content-Type') && options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json');
  }
  // Attach CSRF token for state-changing methods
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrf = getCsrfToken();
    if (csrf) headers.set('X-CSRF-Token', csrf);
  }

  const doFetch = () =>
    fetch(url, { ...options, headers, credentials: 'include' });

  let response = await doFetch();

  // Auto-refresh on 401
  if (response.status === 401) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      // Re-read CSRF since refresh may have set a new one
      const newCsrf = getCsrfToken();
      if (newCsrf && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
        headers.set('X-CSRF-Token', newCsrf);
      }
      response = await doFetch();
    }
  }

  return response;
}

// ---------------------------------------------------------------------------
// Auth API functions
// ---------------------------------------------------------------------------

export async function authSendOtp(
  email: string,
  purpose: 'register' | 'forgot_password',
): Promise<MessageResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/send-otp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, purpose }),
    credentials: 'include',
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Không thể gửi mã OTP.');
  }
  return (await res.json()) as MessageResponse;
}

export async function authRegister(
  email: string,
  password: string,
  otp: string,
  fullName?: string,
  username?: string,
): Promise<MessageResponse> {
  const body: Record<string, string> = { email, password, otp };
  if (fullName) body.full_name = fullName;
  if (username) body.username = username;

  const res = await fetch(`${API_BASE}/api/v1/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    credentials: 'include',
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Đăng ký thất bại.');
  }
  return (await res.json()) as MessageResponse;
}

export async function authResetPassword(
  email: string,
  otp: string,
  newPassword: string,
  confirmPassword: string,
): Promise<MessageResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/reset-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      otp,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
    credentials: 'include',
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Đặt lại mật khẩu thất bại.');
  }
  return (await res.json()) as MessageResponse;
}

export async function authLogin(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
    credentials: 'include',
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Đăng nhập thất bại.');
  }
  return (await res.json()) as AuthResponse;
}

export async function authGoogleLogin(
  code?: string,
  credential?: string,
  redirectUri?: string,
): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/google`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, credential, redirect_uri: redirectUri }),
    credentials: 'include',
  });

  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Đăng nhập bằng Google thất bại.');
  }
  return (await res.json()) as AuthResponse;
}

export async function authRefresh(): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  });

  if (!res.ok) {
    throw new Error('Phiên đăng nhập đã hết hạn.');
  }
  return (await res.json()) as AuthResponse;
}

export async function authLogout(): Promise<void> {
  await fetch(`${API_BASE}/api/v1/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  });
}

export async function authMe(): Promise<UserProfile> {
  const res = await fetchWithAuth(`${API_BASE}/api/v1/auth/me`);
  if (!res.ok) throw new Error('Không thể lấy thông tin người dùng.');
  return (await res.json()) as UserProfile;
}

// ---------------------------------------------------------------------------
// User profile API
// ---------------------------------------------------------------------------

export async function updateProfile(data: {
  full_name?: string;
  username?: string;
  avatar?: string;
}): Promise<UserProfile> {
  const res = await fetchWithAuth(`${API_BASE}/api/v1/users/me`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Cập nhật thất bại.');
  }
  return (await res.json()) as UserProfile;
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
  confirmPassword: string,
): Promise<MessageResponse> {
  const res = await fetchWithAuth(`${API_BASE}/api/v1/users/me/password`, {
    method: 'PATCH',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Đổi mật khẩu thất bại.');
  }
  return (await res.json()) as MessageResponse;
}

// ---------------------------------------------------------------------------
// Admin API
// ---------------------------------------------------------------------------

export interface ServiceStatusItem {
  id: string;
  name: string;
  subTitle: string;
  icon: string;
  status: string;
  uptime: string;
  responseTime: number;
  throughput: string;
  host: string;
  port: number;
  maxConnections: number;
  description: string;
}

export interface SystemStatsResponse {
  total_users: number;
  active_users: number;
  disabled_users: number;
  admin_users: number;
  total_frames: number;
  total_reviews: number;
  total_embeddings: number;
  cpu_usage: number;
  ram_usage: number;
  storage_usage: number;
  storage_total_gb: number;
  storage_free_gb: number;
  services: ServiceStatusItem[];
}

export async function adminGetStats(): Promise<SystemStatsResponse> {
  const res = await fetchWithAuth(`${API_BASE}/api/v1/admin/stats`);
  if (!res.ok) throw new Error('Không thể lấy thống kê hệ thống.');
  return (await res.json()) as SystemStatsResponse;
}

export async function adminListUsers(): Promise<UserProfile[]> {
  const res = await fetchWithAuth(`${API_BASE}/api/v1/admin/users`);
  if (!res.ok) throw new Error('Không có quyền truy cập.');
  return (await res.json()) as UserProfile[];
}

export async function adminCreateUser(data: {
  email: string;
  password: string;
  full_name?: string;
  username?: string;
  role?: string;
  status?: string;
}): Promise<UserProfile> {
  const res = await fetchWithAuth(`${API_BASE}/api/v1/admin/users`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Thêm người dùng thất bại.');
  }
  return (await res.json()) as UserProfile;
}

export async function adminUpdateUser(
  userId: string,
  data: Record<string, string>,
): Promise<UserProfile> {
  const res = await fetchWithAuth(`${API_BASE}/api/v1/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Cập nhật thất bại.');
  }
  return (await res.json()) as UserProfile;
}

export async function adminDeleteUser(userId: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/api/v1/admin/users/${userId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Xóa thất bại.');
  }
}

