// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
/**
 * Lookup utilities for resolving user IDs to display names.
 */

const USER_NAMES: Record<string, string> = {
  // Cognito emails
  "demo+maria@example.com": "Maria Chen",
  "demo+sarah@example.com": "Sarah Johnson",
  "demo+jake@example.com": "Jake Rodriguez",
  "demo+priya@example.com": "Priya Patel",
  "demo+gary@example.com": "Gary Wilson",
  "demo+agent@example.com": "AI Agent",
  // ERPNext usernames
  "Administrator": "System Admin",
  // Legacy mappings
  "maria.chen": "Maria Chen",
  "sarah.johnson": "Sarah Johnson",
  "jake.rodriguez": "Jake Rodriguez",
  "priya.patel": "Priya Patel",
  "gary.wilson": "Gary Wilson",
  // Agent decisions
  "AI_AGENT": "AI Agent",
  "chat_agent": "AI Agent",
};

export function resolveUserName(userId: string): string {
  if (!userId) return "Unknown";
  // Direct lookup
  if (USER_NAMES[userId]) return USER_NAMES[userId];
  // UUID pattern — show "User" instead of raw UUID
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-/.test(userId)) return "Authenticated User";
  return userId;
}
