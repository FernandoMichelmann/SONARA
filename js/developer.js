(() => {
  const API_BASE = (window.SONARA_API_BASE_URL || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");
  const TOKEN_KEY = "sonaraDeveloperAccessToken";
  const $ = id => document.getElementById(id);
  const loginCard = $("loginCard");
  const dashboardCard = $("dashboardCard");
  const loginForm = $("developerLogin");
  const loginMessage = $("formMessage");
  const loginButton = $("submitButton");
  const passwordInput = $("developerPassword");
  let identity = null;
  let userQuery = "";
  let refreshInProgress = false;

  if (window.lucide) window.lucide.createIcons();

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[char]);
  }

  function setMessage(element, text, type = "") {
    element.textContent = text || "";
    element.classList.remove("error", "success");
    if (type) element.classList.add(type);
  }

  function setGlobalMessage(text, type = "") {
    setMessage($("globalMessage"), text, type);
  }

  function formatMoney(value) {
    const number = Number(value || 0);
    return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(number);
  }

  function formatDate(value) {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short", timeStyle: "short"
    }).format(date);
  }

  async function request(path, options = {}, token = sessionStorage.getItem(TOKEN_KEY) || "") {
    const headers = { ...(options.headers || {}) };
    if (token) headers.Authorization = "Bearer " + token;
    const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
    if (options.body && !isFormData && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
    const response = await fetch(API_BASE + path, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(data.detail || data.message || "Não foi possível concluir a operação.");
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function showDashboard(user) {
    identity = user || identity;
    loginCard.hidden = true;
    dashboardCard.hidden = false;
    $("developerIdentity").textContent = identity?.name || identity?.email || "Sessão administrativa validada.";
    $("sidebarIdentity").textContent = identity?.email || "Sessão validada";
    if (window.lucide) window.lucide.createIcons();
  }

  function showLogin() {
    dashboardCard.hidden = true;
    loginCard.hidden = false;
  }

  function setActiveTab(tab) {
    document.querySelectorAll(".nav-item[data-tab]").forEach(button => {
      button.classList.toggle("active", button.dataset.tab === tab);
    });
    document.querySelectorAll(".tab-panel").forEach(panel => {
      panel.hidden = panel.id !== "panel-" + tab;
    });
    const labels = {
      overview: ["Visão geral", "Acompanhe os principais números da plataforma."],
      users: ["Usuários", "Acompanhe as contas que se cadastraram na SONARA."],
      tracks: ["Biblioteca de tracks", "Envie arquivos e controle a publicação no catálogo."],
      revenue: ["Receitas", "Acompanhe os lançamentos financeiros registrados."]
    };
    $("pageTitle").textContent = labels[tab][0];
    $("pageIntro").textContent = labels[tab][1];
    if (window.lucide) window.lucide.createIcons();
  }

  async function loadUsers() {
    const params = new URLSearchParams({ q: userQuery, limit: "200" });
    const data = await request("/developer/users?" + params.toString());
    $("navUserCount").textContent = data.total ?? data.items.length;
    $("overviewUsers").textContent = data.total ?? data.items.length;
    $("usersCount").textContent = (data.total ?? data.items.length) + " usuário(s) encontrado(s).";
    const rows = data.items.map(user => `
      <tr>
        <td><div class="cell-primary">${escapeHtml(user.full_name)}</div><div class="cell-secondary">${escapeHtml(user.email)}</div></td>
        <td>${escapeHtml(formatDate(user.created_at))}</td>
        <td><span class="status-pill ${user.is_active ? "active" : "inactive"}">${user.is_active ? "Ativo" : "Desativado"}</span></td>
        <td><button class="table-action" data-user-status="${user.id}" data-next-active="${user.is_active ? "false" : "true"}">${user.is_active ? "Desativar" : "Reativar"}</button></td>
      </tr>`).join("");
    $("usersTable").innerHTML = rows || '<tr><td colspan="4" class="empty-cell">Nenhum usuário encontrado.</td></tr>';
  }

  async function loadTracks() {
    const data = await request("/developer/tracks");
    const tracks = data.items || [];
    $("overviewTracks").textContent = tracks.length;
    const published = tracks.filter(track => track.is_published).length;
    $("publishedTracks").textContent = published + " publicada(s) no catálogo";
    const rows = tracks.map(track => `
      <tr>
        <td><div class="cell-primary">${escapeHtml(track.title)}</div><div class="cell-secondary">${escapeHtml(track.artist || "Artista não informado")}</div></td>
        <td>${escapeHtml(track.musical_key || "Tom —")} · ${track.bpm ? escapeHtml(track.bpm + " BPM") : "BPM —"}<div class="cell-secondary">${escapeHtml(track.category)}</div></td>
        <td><div class="cell-primary">${escapeHtml(track.original_filename)}</div><div class="cell-secondary">${(Number(track.file_size || 0) / (1024 * 1024)).toFixed(1)} MB</div></td>
        <td><span class="status-pill ${track.is_published ? "published" : "unpublished"}">${track.is_published ? "Publicada" : "Rascunho"}</span></td>
        <td><button class="table-action" data-track-publish="${track.id}" data-next-published="${track.is_published ? "false" : "true"}">${track.is_published ? "Retirar do site" : "Publicar"}</button></td>
      </tr>`).join("");
    $("tracksTable").innerHTML = rows || '<tr><td colspan="5" class="empty-cell">Nenhuma track enviada ainda.</td></tr>';
  }

  async function loadRevenue() {
    const [summary, data] = await Promise.all([
      request("/developer/revenue-summary"),
      request("/developer/revenues?limit=200")
    ]);
    $("revenueReceived").textContent = formatMoney(summary.received_total);
    $("revenuePending").textContent = formatMoney(summary.pending_total);
    $("revenueEntries").textContent = summary.entries_count ?? (data.items || []).length;
    $("overviewRevenue").textContent = formatMoney(summary.received_total);
    $("overviewPending").textContent = formatMoney(summary.pending_total);
    const rows = (data.items || []).map(entry => `
      <tr>
        <td><div class="cell-primary">${escapeHtml(entry.description)}</div></td>
        <td>${escapeHtml(entry.source)}</td>
        <td>${escapeHtml(formatDate(entry.occurred_at))}</td>
        <td><span class="status-pill ${entry.status === "received" ? "received" : "pending"}">${entry.status === "received" ? "Recebido" : "Pendente"}</span></td>
        <td class="cell-primary">${escapeHtml(formatMoney(entry.amount))}</td>
      </tr>`).join("");
    $("revenueTable").innerHTML = rows || '<tr><td colspan="5" class="empty-cell">Nenhum lançamento financeiro registrado.</td></tr>';
  }

  async function refreshAll() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    $("refreshButton").disabled = true;
    setGlobalMessage("Atualizando dados...");
    const results = await Promise.allSettled([loadUsers(), loadTracks(), loadRevenue()]);
    const failed = results.filter(result => result.status === "rejected");
    if (failed.length) {
      setGlobalMessage("Alguns dados não puderam ser carregados. " + failed.map(result => result.reason?.message || "Erro desconhecido").join(" "), "error");
    } else {
      setGlobalMessage("Dados atualizados a partir da API.", "success");
    }
    $("refreshButton").disabled = false;
    refreshInProgress = false;
  }

  async function validateSession() {
    const token = sessionStorage.getItem(TOKEN_KEY);
    if (!token) return;
    try {
      identity = await request("/developer/me", { method: "GET" }, token);
      showDashboard(identity);
      await refreshAll();
    } catch {
      sessionStorage.removeItem(TOKEN_KEY);
      showLogin();
    }
  }

  loginForm.addEventListener("submit", async event => {
    event.preventDefault();
    setMessage(loginMessage, "");
    loginButton.disabled = true;
    loginButton.querySelector("span").textContent = "Validando acesso...";
    try {
      const result = await request("/developer/login", {
        method: "POST",
        body: JSON.stringify({
          email: $("developerEmail").value.trim(),
          password: passwordInput.value
        })
      }, "");
      if (!result.access_token) throw new Error("O servidor não retornou um token válido.");
      sessionStorage.setItem(TOKEN_KEY, result.access_token);
      passwordInput.value = "";
      identity = await request("/developer/me", { method: "GET" }, result.access_token);
      showDashboard(identity);
      await refreshAll();
    } catch (error) {
      if (error instanceof TypeError) setMessage(loginMessage, "Não foi possível conectar à API. Verifique se o backend está ativo.");
      else if (error.status === 401 || error.status === 403) setMessage(loginMessage, "Credenciais inválidas ou acesso sem permissão de desenvolvedor.");
      else setMessage(loginMessage, error.message || "Falha ao autenticar.");
    } finally {
      loginButton.disabled = false;
      loginButton.querySelector("span").textContent = "Entrar no ambiente privado";
    }
  });

  $("togglePassword").addEventListener("click", () => {
    const visible = passwordInput.type === "text";
    passwordInput.type = visible ? "password" : "text";
    $("togglePassword").setAttribute("aria-label", visible ? "Mostrar senha" : "Ocultar senha");
    $("togglePassword").innerHTML = visible ? '<i data-lucide="eye"></i>' : '<i data-lucide="eye-off"></i>';
    if (window.lucide) window.lucide.createIcons();
  });

  document.querySelectorAll(".nav-item[data-tab]").forEach(button => {
    button.addEventListener("click", () => setActiveTab(button.dataset.tab));
  });
  $("refreshButton").addEventListener("click", refreshAll);
  $("logoutButton").addEventListener("click", () => {
    sessionStorage.removeItem(TOKEN_KEY);
    identity = null;
    showLogin();
    setMessage(loginMessage, "Sessão encerrada.", "success");
  });

  let searchTimer;
  $("userSearch").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      userQuery = $("userSearch").value.trim();
      try { await loadUsers(); }
      catch (error) { setGlobalMessage(error.message, "error"); }
    }, 250);
  });

  $("usersTable").addEventListener("click", async event => {
    const button = event.target.closest("[data-user-status]");
    if (!button) return;
    button.disabled = true;
    try {
      await request("/developer/users/" + button.dataset.userStatus + "/status", {
        method: "PATCH",
        body: JSON.stringify({ is_active: button.dataset.nextActive === "true" })
      });
      setGlobalMessage("Status do usuário atualizado.", "success");
      await loadUsers();
    } catch (error) {
      setGlobalMessage(error.message, "error");
      button.disabled = false;
    }
  });

  $("trackUploadForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $("uploadTrackButton");
    const message = $("trackUploadMessage");
    const formData = new FormData(form);
    formData.set("is_published", $("trackPublish").checked ? "true" : "false");
    if (!$("trackBpm").value) formData.delete("bpm");
    button.disabled = true;
    button.querySelector("span").textContent = "Enviando arquivo...";
    setMessage(message, "O upload pode levar alguns instantes para arquivos grandes.");
    try {
      await request("/developer/tracks", { method: "POST", body: formData });
      form.reset();
      $("trackCategory").value = "Multitrack";
      setMessage(message, "Track enviada com sucesso.", "success");
      setGlobalMessage("Biblioteca de tracks atualizada.", "success");
      await Promise.all([loadTracks()]);
    } catch (error) {
      setMessage(message, error.message || "Não foi possível enviar a track.", "error");
    } finally {
      button.disabled = false;
      button.querySelector("span").textContent = "Enviar track";
    }
  });

  $("tracksTable").addEventListener("click", async event => {
    const button = event.target.closest("[data-track-publish]");
    if (!button) return;
    button.disabled = true;
    const formData = new FormData();
    formData.set("is_published", button.dataset.nextPublished);
    try {
      await request("/developer/tracks/" + button.dataset.trackPublish, { method: "PATCH", body: formData });
      setGlobalMessage("Status de publicação atualizado.", "success");
      await loadTracks();
    } catch (error) {
      setGlobalMessage(error.message, "error");
      button.disabled = false;
    }
  });

  $("revenueForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $("saveRevenueButton");
    const message = $("revenueFormMessage");
    const amount = Number($("revenueAmount").value);
    if (!Number.isFinite(amount) || amount <= 0) {
      setMessage(message, "Informe um valor maior que zero.", "error");
      return;
    }
    button.disabled = true;
    try {
      await request("/developer/revenues", {
        method: "POST",
        body: JSON.stringify({
          description: $("revenueDescription").value.trim(),
          source: $("revenueSource").value,
          amount: amount.toFixed(2),
          status: $("revenueStatus").value
        })
      });
      form.reset();
      setMessage(message, "Lançamento registrado.", "success");
      setGlobalMessage("Histórico financeiro atualizado.", "success");
      await loadRevenue();
    } catch (error) {
      setMessage(message, error.message || "Não foi possível registrar o lançamento.", "error");
    } finally {
      button.disabled = false;
    }
  });

  validateSession();
})();