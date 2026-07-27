// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import { Amplify } from "aws-amplify";
import {
  signIn,
  signOut,
  getCurrentUser,
  fetchAuthSession,
  fetchUserAttributes,
} from "aws-amplify/auth";

Amplify.configure({
  Auth: {
    Cognito: {
      userPoolId: import.meta.env.VITE_COGNITO_POOL_ID || "",
      userPoolClientId: import.meta.env.VITE_COGNITO_CLIENT_ID || "",
      identityPoolId: import.meta.env.VITE_COGNITO_IDENTITY_POOL_ID || "",
    },
  },
});

// Local-dev guest mode: the local/ harness injects window.ARIA_CONFIG.localMode
// (via public/local-config.js) so the SPA runs without Cognito. In that mode the
// auth functions below return a demo user and skip Amplify entirely. Deployed
// builds never set ARIA_CONFIG, so this whole branch is dead code in production.
export interface AuthUser {
  username: string;
  displayName: string;
  email: string;
  role: string;
  sapUser: string;
  department: string;
}

// Local-dev guest mode: the local/ harness injects window.ARIA_CONFIG.localMode
// (via public/local-config.js) so the SPA runs without Cognito. In that mode the
// auth functions below return a demo user and skip Amplify entirely. Deployed
// builds never set ARIA_CONFIG, so this whole branch is dead code in production.
interface AriaLocalConfig {
  localMode?: boolean;
  demoUser?: Partial<AuthUser>;
}
const LOCAL_CONFIG: AriaLocalConfig =
  (typeof window !== "undefined" &&
    (window as unknown as { ARIA_CONFIG?: AriaLocalConfig }).ARIA_CONFIG) ||
  {};

const GUEST_USER: AuthUser = {
  username: "demo+jake@example.com",
  displayName: "Jake Rodriguez",
  email: "demo+jake@example.com",
  role: "procurement",
  sapUser: "",
  department: "Procurement",
  ...(LOCAL_CONFIG.demoUser || {}),
};

export async function login(username: string, _password: string): Promise<AuthUser> {
  if (LOCAL_CONFIG.localMode) {
    // Accept any demo persona email; pick the matching role client-side.
    return { ...GUEST_USER, username, email: username };
  }
  await signIn({ username, password: _password });
  return getAuthUser();
}

export async function logout(): Promise<void> {
  if (LOCAL_CONFIG.localMode) return;
  await signOut();
}

export async function getAuthUser(): Promise<AuthUser> {
  if (LOCAL_CONFIG.localMode) return GUEST_USER;
  const user = await getCurrentUser();
  const attrs = await fetchUserAttributes();
  const givenName = attrs.given_name || "";
  const familyName = attrs.family_name || "";
  const displayName = givenName && familyName
    ? `${givenName} ${familyName}`
    : attrs.email?.split("@")[0]?.replace("demo+", "") || user.username;
  return {
    username: attrs.email || user.username,
    displayName,
    email: attrs.email || "",
    role: attrs["custom:role"] || "",
    sapUser: attrs["custom:sap_user"] || "",
    department: attrs["custom:department"] || "",
  };
}

export async function getToken(): Promise<string | null> {
  try {
    const session = await fetchAuthSession();
    return session.tokens?.idToken?.toString() || null;
  } catch {
    return null;
  }
}

export async function getAccessToken(): Promise<string | null> {
  try {
    const session = await fetchAuthSession();
    return session.tokens?.accessToken?.toString() || null;
  } catch {
    return null;
  }
}

export async function isAuthenticated(): Promise<boolean> {
  if (LOCAL_CONFIG.localMode) return true;
  try {
    await getCurrentUser();
    return true;
  } catch {
    return false;
  }
}

/** Get temporary AWS credentials from Cognito Identity Pool for SigV4 signing. */
export async function getAwsCredentials(): Promise<{
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken: string;
} | null> {
  try {
    const session = await fetchAuthSession();
    const creds = session.credentials;
    if (creds?.accessKeyId && creds?.secretAccessKey && creds?.sessionToken) {
      return {
        accessKeyId: creds.accessKeyId,
        secretAccessKey: creds.secretAccessKey,
        sessionToken: creds.sessionToken,
      };
    }
    return null;
  } catch {
    return null;
  }
}
