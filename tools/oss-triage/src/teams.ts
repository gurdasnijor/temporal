export const TEAMS = ["oss-matching", "oss-foundations", "act", "nexus", "cgs"] as const;
export type Team = (typeof TEAMS)[number];

export const isTeam = (name: string): name is Team => (TEAMS as readonly string[]).includes(name);

/** GitHub login (lowercase) to the current teams that person is on. */
export type Membership = Map<string, Set<Team>>;

export const teamsOf = (membership: Membership, login: string | null | undefined): Set<Team> =>
  membership.get((login ?? "").toLowerCase()) ?? new Set();
