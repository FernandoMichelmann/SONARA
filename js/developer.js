/*
 * SONARA Developer Console
 * Security contract:
 * POST /api/v1/developer/login -> { access_token, token_type }
 * GET  /api/v1/developer/me    -> { email, name? }
 *
 * These endpoints must be implemented by the backend. No credentials or
 * authorization decisions are stored in this frontend.
 */
(() => {
  const API_BASE = (window.SONARA_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");
  const TOKEN_KEY = "sonaraDeveloperAccessToken";
  const loginCard = document.getElementById("loginCard");
  const dashboardCard = document.getElementById("dashboardCard");
  const form = document.getElementById("developerLogin");
  const message = document.getElementById("formMessage");
  const submitButton = document.getElementById("submitButton");
  const passwordInput = document.getElementById("developerPassword");

  if (window.lucide) window.lucide.createIcons();

  function setMessage(text, isError = true) {
    message.textContent = text;
    message.style.color = isError ? "var(--danger)" : "var(--green)";
  }

  function showDashboard(identity) {
    loginCard.hidden = true;
    dashboardCard.hidden = false;
    document.getElementById("developerIdentity").textContent =
      identity?.name || identity?.email || "Identidade administrativa confirmada.";
    if (window.lucide) window.lucide.createIcons();
  }

  function showLogin() {
    dashboardCard.hidden = true;
    loginCard.hidden = false;
  }

  async function request(path, options = {}, token = "") {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (token) headers.Authorization = "Bearer " + token;
    const response = await fetch(API_BASE + path, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.detail || data.message || "Não foi possível validar o acesso.");
      error.status = response.status;
      throw error;
    }
    return data;
  }

  async function validateSession() {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) return;
    try {
      const identity = await request("/developer/me", { method: "GET" }, token);
      showDashboard(identity);
    } catch {
      sessionStorage.removeItem(TOKEN_KEY);
      showLogin();
    }
  }

  form.addEventListener("submit", async event => {
    event.preventDefault();
    setMessage("");
    submitButton.disabled = true;
    submitButton.querySelector("span").textContent = "Validando acesso...";
    const email = document.getElementById("developerEmail").value.trim();
    const password = passwordInput.value;

    try {
      const result = await request("/developer/login", {
        method: "POST",
        body: JSON.stringify({ email, password })
      });
      if (!result.access_token) throw new Error("O servidor não retornou um token de acesso válido.");
      sessionStorage.setItem(TOKEN_KEY, result.access_token);
      passwordInput.value = "";
      const identity = await request("/developer/me", { method: "GET" }, result.access_token);
      showDashboard(identity);
    } catch (error) {
      if (error instanceof TypeError) {
        setMessage("Não foi possível conectar ao servidor. A autenticação administrativa precisa estar ativa no backend.");
      } else if (error.status === 404) {
        setMessage("A tela está pronta, mas os endpoints de autenticação do desenvolvedor ainda não foram implementados no backend.");
      } else if (error.status === 401 || error.status === 403) {
        setMessage("Credenciais inválidas ou usuário sem permissão de desenvolvedor.");
      } else {
        setMessage(error.message || "Falha ao autenticar.");
      }
    } finally {
      submitButton.disabled = false;
      submitButton.querySelector("span").textContent = "Entrar no ambiente privado";
    }
  });

  document.getElementById("togglePassword").addEventListener("click", () => {
    const visible = passwordInput.type === "text";
    passwordInput.type = visible ? "password" : "text";
    document.getElementById("togglePassword").setAttribute("aria-label", visible ? "Mostrar senha" : "Ocultar senha");
    document.getElementById("togglePassword").innerHTML = visible
      ? '<i data-lucide="eye"></i>' : '<i data-lucide="eye-off"></i>';
    if (window.lucide) window.lucide.createIcons();
  });

  document.getElementById("logoutButton").addEventListener("click", () => {
    sessionStorage.removeItem(TOKEN_KEY);
    showLogin();
    setMessage("Sessão encerrada.", false);
  });

  validateSession();
})();
