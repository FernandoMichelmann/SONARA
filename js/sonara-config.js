/* SONARA API endpoint configuration.
 *
 * Local development:
 *   Live Server (localhost/127.0.0.1) uses the local FastAPI backend.
 *
 * Public GitHub Pages:
 *   Do NOT point visitors to 127.0.0.1: that address is each visitor's own
 *   computer. Set PUBLIC_API to the deployed HTTPS backend URL once the API
 *   has been hosted (example format: https://your-api.example.com/api/v1).
 */
(() => {
  const hostname = window.location.hostname;
  const isLocalPage = ["localhost", "127.0.0.1"].includes(hostname);

  // TODO: Replace with the actual public backend URL after backend deployment.
  const PUBLIC_API = "";
  const localApi = "http://127.0.0.1:8000/api/v1";

  const apiBase = PUBLIC_API.trim()
    ? PUBLIC_API.trim().replace(/\/$/, "")
    : (isLocalPage ? localApi : "");

  window.SONARA_API_BASE_URL = apiBase;
  window.SONARA_API_MODE = apiBase
    ? (isLocalPage ? "local" : "public")
    : "not-configured";
})();
