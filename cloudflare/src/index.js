var SYSTEM_PROMPT = "You are a helpful AI assistant. Answer in the same language as the user unless asked otherwise. Be accurate, clear, and practical. If you are unsure, say so.";

function json(data, status) {
  return new Response(JSON.stringify(data), {
    status: status || 200,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" }
  });
}

function isValidMessage(message) {
  return message &&
    (message.role === "user" || message.role === "assistant") &&
    typeof message.content === "string" &&
    message.content.length > 0 &&
    message.content.length <= 20000;
}

function trimMessages(messages) {
  var result = [];
  var total = 0;
  var i;
  for (i = messages.length - 1; i >= 0 && result.length < 30; i--) {
    if (!isValidMessage(messages[i])) continue;
    if (total + messages[i].content.length > 60000) break;
    result.unshift({ role: messages[i].role, content: messages[i].content });
    total += messages[i].content.length;
  }
  return result;
}

async function handleChat(request, env) {
  if (request.method !== "POST") {
    return json({ error: "Method not allowed" }, 405);
  }

  if (env.ACCESS_KEY) {
    var suppliedKey = request.headers.get("X-Access-Key") || "";
    if (suppliedKey !== env.ACCESS_KEY) {
      return json({ error: "נדרש מפתח גישה תקין. פתח את ההגדרות והזן את המפתח." }, 401);
    }
  }

  var length = Number(request.headers.get("Content-Length") || "0");
  if (length > 180000) {
    return json({ error: "הבקשה גדולה מדי. קצר את היסטוריית השיחה." }, 413);
  }

  var payload;
  try {
    payload = await request.json();
  } catch (e) {
    return json({ error: "Invalid JSON body" }, 400);
  }

  if (!payload || !Array.isArray(payload.messages)) {
    return json({ error: "messages must be an array" }, 400);
  }

  var messages = trimMessages(payload.messages);
  if (!messages.length || messages[messages.length - 1].role !== "user") {
    return json({ error: "A user message is required" }, 400);
  }

  if (!env.AI || typeof env.AI.run !== "function") {
    return json({ error: "Workers AI binding is not configured" }, 503);
  }

  var model = env.DEFAULT_MODEL || "@cf/zai-org/glm-4.7-flash";
  var modelMessages = [{ role: "system", content: SYSTEM_PROMPT }].concat(messages);

  try {
    var stream = await env.AI.run(model, {
      messages: modelMessages,
      stream: true,
      max_tokens: 4096,
      temperature: 0.7
    });

    return new Response(stream, {
      status: 200,
      headers: {
        "content-type": "text/event-stream; charset=utf-8",
        "cache-control": "no-cache, no-transform",
        "x-content-type-options": "nosniff",
        "x-accel-buffering": "no"
      }
    });
  } catch (error) {
    return json({
      error: "Workers AI request failed",
      detail: error && error.message ? error.message : String(error)
    }, 502);
  }
}

export default {
  async fetch(request, env) {
    var url = new URL(request.url);

    if (url.pathname === "/api/health") {
      return json({
        ok: true,
        provider: "workers-ai",
        model: env.DEFAULT_MODEL || "@cf/zai-org/glm-4.7-flash",
        requiresKey: !!env.ACCESS_KEY
      });
    }

    if (url.pathname === "/api/chat") {
      return handleChat(request, env);
    }

    if (url.pathname.indexOf("/api/") === 0) {
      return json({ error: "Not found" }, 404);
    }

    return env.ASSETS.fetch(request);
  }
};
