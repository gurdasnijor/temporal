import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { test } from "node:test";
import type { AgentSessionEventWebhookPayload } from "@linear/sdk";
import type { Route, Router } from "../router.ts";
import { handleSession, suggestion, webhookHandler, type Activity } from "./agent.ts";

const route: Route = {
  team: "oss-matching",
  runnerUp: "oss-foundations",
  score: 0.5,
  margin: 0.2,
  confidence: "high",
  scores: { "oss-matching": 0.5, "oss-foundations": 0.3, act: 0, nexus: 0, cgs: 0 },
  files: [{ path: "service/matching/matcher.go", owners: ["oss-matching"] }],
};

const event = (fields: object) =>
  ({
    type: "AgentSessionEvent",
    action: "created",
    webhookTimestamp: Date.now(),
    agentSession: { id: "s1", issue: { title: "Tasks stuck", description: "in matching" } },
    ...fields,
  }) as unknown as AgentSessionEventWebhookPayload;

function recorder() {
  const posted: Activity[] = [];
  return { posted, post: async (_: string, activity: Activity) => void posted.push(activity) };
}

test("thinks first, then answers with the team and its evidence", async () => {
  const { posted, post } = recorder();
  await handleSession(event({}), async () => route, post);
  assert.deepEqual(posted.map((a) => a.type), ["thought", "response"]);
  assert.match(posted[1]!.body, /Suggested team: oss-matching/);
  assert.match(posted[1]!.body, /service\/matching\/matcher\.go/);
});

test("low confidence never reads as a suggestion", () => {
  const body = suggestion({ ...route, confidence: "low" });
  assert.match(body, /No confident team/);
  assert.doesNotMatch(body, /Suggested team/);
});

test("no evidence names no team", () => {
  const body = suggestion({ ...route, confidence: "low", score: 0 });
  assert.match(body, /No ownership evidence/);
  assert.doesNotMatch(body, /oss-matching\b.*then/);
});

test("a follow-up reply joins the issue text", async () => {
  const { post } = recorder();
  let seen = "";
  const router: Router = async (issue) => ((seen = issue.body ?? ""), route);
  await handleSession(event({ action: "prompted", agentActivity: { content: { body: "it is the poller" } } }), router, post);
  assert.equal(seen, "in matching\n\nit is the poller");
});

test("stop halts without routing", async () => {
  const { posted, post } = recorder();
  const router: Router = async () => assert.fail("routed after stop");
  await handleSession(event({ action: "prompted", agentActivity: { signal: "stop", content: {} } }), router, post);
  assert.deepEqual(posted.map((a) => a.type), ["response"]);
});

test("a routing failure reaches the session as an error", async () => {
  const { posted, post } = recorder();
  await handleSession(event({}), async () => { throw new Error("index down"); }, post);
  assert.equal(posted.at(-1)?.type, "error");
  assert.match(posted.at(-1)!.body, /index down/);
});

test("the real webhook client verifies the signature, then the session runs", async () => {
  const { posted, post } = recorder();
  const handler = webhookHandler("secret", async () => route, post);
  const body = JSON.stringify(event({}));
  const request = (signature: string) =>
    new Request("http://agent/webhook", {
      method: "POST",
      body,
      headers: { "linear-signature": signature, "linear-event": "AgentSessionEvent" },
    });

  assert.notEqual((await handler(request("0".repeat(64)))).status, 200);
  assert.equal(posted.length, 0);

  const response = await handler(request(createHmac("sha256", "secret").update(body).digest("hex")));
  assert.equal(response.status, 200);
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(posted.map((a) => a.type), ["thought", "response"]);
});
