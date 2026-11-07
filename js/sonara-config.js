/* SONARA API endpoint configuration.
 * Local development uses the Mac backend automatically.
 * For GitHub Pages/mobile testing, set the public HTTPS tunnel URL here,
 * including /api/v1. Example: https://your-tunnel.trycloudflare.com/api/v1
 */
(() => {
  const isLocal = ["localhost", "127.0.0.1"].includes(window.location.hostname);
  const configured = "";
  window.SONARA_API_BASE_URL = configured
    ? configured.replace(/\/$/, "")
    : (isLocal ? "http://127.0.0.1:8000/api/v1" : "");
})();
