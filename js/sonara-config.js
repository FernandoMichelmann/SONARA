/* SONARA API endpoint configuration.
 * Test mode: GitHub Pages opened on the development Mac talks to its local backend.
 * For mobile/external access, replace the fallback with the public HTTPS tunnel URL.
 */
(() => {
  const hostname = window.location.hostname;
  const isLocalPage = ["localhost", "127.0.0.1"].includes(hostname);
  const configured = "";
  const localApi = "http://127.0.0.1:8000/api/v1";
  const apiBase = configured.trim()
    ? configured.trim().replace(/\/$/, "")
    : localApi;
  window.SONARA_API_BASE_URL = apiBase;
  window.SONARA_API_MODE = isLocalPage ? "local" : "local-backend-from-pages";
})();
