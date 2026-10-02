// Remove formatações Markdown ([url](url)) que a Vercel/cola de texto às vezes injeta nas variáveis.
function sanitizeEnvUrl(urlStr) {
  if (!urlStr) return "";
  const match = urlStr.match(/^\[.*?\]\((.*?)\)$/);
  return (match ? match[1] : urlStr).trim().replace(/\/$/, "");
}

/** HTTP base do FastAPI */
export function backendHttpBase() {
  const rawApi = process.env.NEXT_PUBLIC_API_URL;
  if (rawApi) return sanitizeEnvUrl(rawApi);
  const wsUrl = sanitizeEnvUrl(process.env.NEXT_PUBLIC_WS_URL) || "ws://127.0.0.1:10000/ws";
  return wsUrl.replace(/^wss:\/\//i, "https://").replace(/^ws:\/\//i, "http://").replace(/\/ws\/?$/i, "");
}

/** WebSocket do backend */
export function backendWsUrl() {
  const rawWs = process.env.NEXT_PUBLIC_WS_URL;
  if (rawWs) return sanitizeEnvUrl(rawWs);
  const api = backendHttpBase();
  const host = api.includes("://") ? api.split("://")[1] : api;
  return `${/^https:/i.test(api) ? "wss" : "ws"}://${host}/ws`;
}
