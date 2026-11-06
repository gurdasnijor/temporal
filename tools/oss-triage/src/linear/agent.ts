import type { AgentSessionEventWebhookPayload } from "@linear/sdk";
import { LinearWebhookClient } from "@linear/sdk/webhooks";
import type { Route, Router } from "../router.ts";

export type Activity = { type: "thought" | "response" | "error"; body: string };

/** Sends one activity to a Linear agent session. */
export type Post = (agentSessionId: string, content: Activity) => Promise<unknown>;

const NOT_CHANGED = "Suggestion only: this issue was not changed.";

const headline = ({ team, runnerUp, confidence, score }: Route): string => {
  if (score === 0) return "**No ownership evidence.** Nothing the search found has a known team.";
  if (confidence === "low") return `**No confident team.** Best guess: ${team}, then ${runnerUp}.`;
  return `**Suggested team: ${team}** (${confidence === "high" ? "likely" : "possible"}). Runner-up: ${runnerUp}.`;
};

export function suggestion(route: Route): string {
  const evidence = route.files.map(({ path, owners }) => `- \`${path}\` (${owners.join(", ") || "no owner"})`);
  return [headline(route), `Score ${route.score.toFixed(2)}, margin ${route.margin.toFixed(2)}.`, "Closest code:", evidence.join("\n"), NOT_CHANGED].join("\n\n");
}

/**
 * Answers one session event. Never changes the issue: Linear asks agents that automations delegate
 * to to keep the issue in triage and leave assignment to a person.
 */
export async function handleSession(event: AgentSessionEventWebhookPayload, route: Router, post: Post): Promise<void> {
  const { id, issue } = event.agentSession;
  const activity = event.agentActivity;

  if (event.action === "prompted" && activity?.signal === "stop") {
    await post(id, { type: "response", body: `Stopped. ${NOT_CHANGED}` });
    return;
  }
  if (!issue) {
    await post(id, { type: "error", body: "This session has no issue to route." });
    return;
  }

  await post(id, { type: "thought", body: "Searching the code and its owners." });
  const reply = event.action === "prompted" ? String(activity?.content.body ?? "") : "";
  const body = [issue.description, reply].filter(Boolean).join("\n\n");
  try {
    await post(id, { type: "response", body: suggestion(await route({ title: issue.title, body })) });
  } catch (error) {
    await post(id, { type: "error", body: `Routing failed: ${error instanceof Error ? error.message : error}` });
  }
}

/**
 * Verifies Linear's signature and hands sessions over. Linear wants the webhook answered in 5 s,
 * so the work is not awaited here; the first activity has to land within 10 s.
 */
export function webhookHandler(secret: string, route: Router, post: Post) {
  const handler = new LinearWebhookClient(secret).createHandler();
  handler.on("AgentSessionEvent", (event) => {
    handleSession(event, route, post).catch((error) => console.error(`session ${event.agentSession.id}:`, error));
  });
  return handler;
}
