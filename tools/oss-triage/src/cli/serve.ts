/**
 * The Linear agent: POST /webhook takes agent session events.
 *
 * Needs LINEAR_WEBHOOK_SECRET and LINEAR_ACCESS_TOKEN (an `actor=app` install), plus what
 * src/cli/route.ts needs. Ownership loads once at startup, so restart it to pick up new commits.
 */
import { createServer } from "node:http";
import { LinearClient } from "@linear/sdk";
import { webhookHandler } from "../linear/agent.ts";
import { loadRouter } from "../service.ts";

const linear = new LinearClient({ accessToken: process.env.LINEAR_ACCESS_TOKEN! });
const handler = webhookHandler(process.env.LINEAR_WEBHOOK_SECRET!, await loadRouter(), (agentSessionId, content) =>
  linear.createAgentActivity({ agentSessionId, content }),
);

const port = Number(process.env.PORT ?? 8790);
createServer((request, response) => {
  if (request.method === "POST" && request.url === "/webhook") return void handler(request, response);
  response.writeHead(404).end();
}).listen(port, () => console.log(`listening on ${port}`));
