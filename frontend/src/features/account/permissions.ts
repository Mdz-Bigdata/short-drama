/** What the login says this person may do. The backend decides; this only keeps the interface honest about it. */
export function hasPermission(user: { permissions?: string[] } | null | undefined, permission: string): boolean {
  return Boolean(user?.permissions?.includes(permission));
}
