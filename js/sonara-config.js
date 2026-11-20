/* SONARA API endpoint configuration.
 *
 * Local development:
 *   localhost/127.0.0.1 uses the local FastAPI backend.
 *
 * LAN development:
 *   When the frontend is opened through the Mac's private network IP,
 *   use that same host for the API on port 8000.
 *
 * Public GitHub Pages:
 *   A public HTTPS backend must be configured separately before Pages can
 *   use the API. Never point public visitors to a private LAN address.
 */
(() => {
  const hostname = window.location.hostname;
  const isLocalPage = ["localhost", "127.0.0.1"].includes(hostname);
  const isPrivateLanHost =
    /^192\.168\./.test(hostname) ||
    /^10\./.test(hostname) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(hostname);

  // TODO: Set this only after deploying a public HTTPS API.
  const PUBLIC_API = "";
  const localApi = "http://127.0.0.1:8000/api/v1";
  const lanApi = `http://${hostname}:8000/api/v1`;

  const apiBase = PUBLIC_API.trim()
    ? PUBLIC_API.trim().replace(/\/$/, "")
    : (isLocalPage ? localApi : (isPrivateLanHost ? lanApi : ""));

  window.SONARA_API_BASE_URL = apiBase;
  window.SONARA_API_MODE = apiBase
    ? (isLocalPage ? "local" : (isPrivateLanHost ? "lan" : "public"))
    : "not-configured";
})();
