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
  let pendingPreviewTrack = null;
  let previewPublishAfter = false;
  let previewSourceObjectUrl = null;
  let previewStart = 0;

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
    const results = await Promise.all([request("/developer/tracks"), request("/developer/track-categories")]);
    const tracks = results[0].items || [];
    renderCategoryOptions(results[1].items || []);
    $("overviewTracks").textContent = tracks.length;
    const published = tracks.filter(track => track.is_published).length;
    $("publishedTracks").textContent = published + " publicada(s) no catálogo";
    const rows = tracks.map(track => {
      const tags = (track.categories || []).map(tag => '<span class="tag-pill">' + escapeHtml(tag) + '</span>').join(" ");
      return '<tr>' +
        '<td><div class="cell-primary">' + escapeHtml(track.title) + '</div><div class="cell-secondary">' + escapeHtml(track.artist || "Artista não informado") + '</div></td>' +
        '<td>' + escapeHtml(track.musical_key || "Tom —") + ' · ' + (track.bpm ? escapeHtml(track.bpm + " BPM") : "BPM —") + '<div class="cell-secondary">' + escapeHtml(track.time_signature || "4/4") + '</div></td>' +
        '<td><div class="tag-list">' + (tags || "—") + '</div></td>' +
        '<td>' + (track.stems || []).length + ' arquivo(s)<div class="cell-secondary">' + escapeHtml(track.original_filename) + '</div></td>' +
        '<td><span class="status-pill ' + (track.is_published ? "published" : "unpublished") + '">' + (track.is_published ? "Publicada" : "Rascunho") + '</span><div class="cell-secondary">' + (track.preview_ready ? "Prévia de 30s pronta" : "Prévia ainda não configurada") + '</div></td>' +
        '<td>' +
          '<button class="table-action" data-track-preview="' + track.id + '"> ' + (track.preview_ready ? "Editar prévia" : "Configurar prévia") + '</button> ' +
          (track.preview_ready ? '<button class="table-action" data-track-publish="' + track.id + '" data-next-published="' + (track.is_published ? "false" : "true") + '">' + (track.is_published ? "Retirar do site" : "Publicar") + '</button>' : '') +
          '<button class="table-action danger" data-track-delete="' + track.id + '">Excluir track</button>' +
        '</td></tr>';
    }).join("");
    $("tracksTable").innerHTML = rows || '<tr><td colspan="6" class="empty-cell">Nenhuma track enviada ainda.</td></tr>';
  }

  function renderCategoryOptions(categories) {
    const container = $("trackCategoryOptions");
    const selected = new Set([...container.querySelectorAll("input:checked")].map(input => input.value));
    container.innerHTML = categories.map(category =>
      '<label class="category-option"><input type="checkbox" value="' + escapeHtml(category.name) + '" ' +
      (selected.has(category.name) ? "checked" : "") + '><span>' + escapeHtml(category.name) + '</span></label>'
    ).join("") || '<span class="muted">Nenhuma categoria cadastrada.</span>';
  }

  async function loadTrackCategories() {
    const data = await request("/developer/track-categories");
    renderCategoryOptions(data.items || []);
  }

  function setTrackStep(step) {
    document.querySelectorAll(".track-form-step").forEach(panel => panel.hidden = panel.id !== "trackStep-" + step);
    document.querySelectorAll(".track-form-tab").forEach(tab => tab.classList.toggle("active", tab.dataset.trackStep === step));
    if (window.lucide) window.lucide.createIcons();
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

  document.querySelectorAll("[data-track-step]").forEach(button => button.addEventListener("click", () => setTrackStep(button.dataset.trackStep)));
  document.querySelectorAll("[data-track-next]").forEach(button => button.addEventListener("click", () => {
    const next = button.dataset.trackNext;
    if (next === "audio" && !$("trackTitle").value.trim()) {
      setMessage($("trackUploadMessage"), "Informe pelo menos o nome da track.", "error");
      setTrackStep("details");
      $("trackTitle").focus();
      return;
    }
    if (next === "cover" && !$("trackArchive").files.length) {
      setMessage($("trackUploadMessage"), "Selecione o pacote ZIP antes de continuar.", "error");
      setTrackStep("audio");
      return;
    }
    setMessage($("trackUploadMessage"), "");
    setTrackStep(next);
  }));
  document.querySelectorAll("[data-track-prev]").forEach(button => button.addEventListener("click", () => setTrackStep(button.dataset.trackPrev)));

  $("addTrackCategory").addEventListener("click", async () => {
    const input = $("newTrackCategory");
    const name = input.value.trim();
    if (!name) return;
    const button = $("addTrackCategory");
    button.disabled = true;
    try {
      await request("/developer/track-categories", { method: "POST", body: JSON.stringify({ name }) });
      input.value = "";
      await loadTrackCategories();
      const checkbox = [...$("trackCategoryOptions").querySelectorAll("input")].find(item => item.value.toLowerCase() === name.toLowerCase());
      if (checkbox) checkbox.checked = true;
      setMessage($("trackUploadMessage"), "Categoria adicionada à biblioteca.", "success");
    } catch (error) {
      setMessage($("trackUploadMessage"), error.message, "error");
    } finally { button.disabled = false; }
  });

  $("trackArchive").addEventListener("change", () => {
    $("archiveSelection").textContent = $("trackArchive").files[0]?.name || "Nenhum pacote selecionado";
  });
  let coverPreviewUrl = null;
  $("trackCover").addEventListener("change", () => {
    const file = $("trackCover").files[0];
    $("coverSelection").textContent = file?.name || "Nenhuma imagem selecionada";
    const preview = $("trackCoverPreview");
    if (coverPreviewUrl) URL.revokeObjectURL(coverPreviewUrl);
    if (!file) {
      preview.innerHTML = '<i data-lucide="image-plus"></i><span>Prévia da capa</span>';
    } else {
      coverPreviewUrl = URL.createObjectURL(file);
      preview.innerHTML = '<img alt="Prévia da capa" src="' + coverPreviewUrl + '">';
    }
    if (window.lucide) window.lucide.createIcons();
  });

  $("trackUploadForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = $("uploadTrackButton");
    const message = $("trackUploadMessage");
    if (!$("trackArchive").files.length) {
      setMessage(message, "Selecione um arquivo ZIP com os stems.", "error");
      setTrackStep("audio");
      return;
    }
    const formData = new FormData(form);
    const selectedCategories = [...$("trackCategoryOptions").querySelectorAll("input:checked")].map(input => input.value);
    formData.set("categories", JSON.stringify(selectedCategories));
    formData.set("is_published", $("trackPublish").checked ? "true" : "false");
    if (!$("trackBpm").value) formData.delete("bpm");
    if (!$("trackCover").files.length) formData.delete("cover");
    button.disabled = true;
    button.querySelector("span").textContent = "Enviando e extraindo ZIP...";
    setMessage(message, "O sistema está validando e organizando os stems. Aguarde o término do envio.");
    try {
      const uploadedResponse = await request("/developer/tracks", { method: "POST", body: formData });
      const uploadedTrack = uploadedResponse.track || uploadedResponse.item || uploadedResponse;
      if (!uploadedTrack || !uploadedTrack.id) throw new Error("O servidor recebeu o ZIP, mas não retornou o identificador da multitrack. Atualize a lista e configure a prévia por lá.");
      pendingPreviewTrack = uploadedTrack;
      previewPublishAfter = $("trackPublish").checked;
      $("previewPublishToggle").checked = previewPublishAfter;
      form.reset();
      $("archiveSelection").textContent = "Nenhum pacote selecionado";
      $("coverSelection").textContent = "Nenhuma imagem selecionada";
      $("trackCoverPreview").innerHTML = '<i data-lucide="image-plus"></i><span>Prévia da capa</span>';
      setTrackStep("details");
      setMessage(message, "Arquivos recebidos. Agora escolha o trecho de 30 segundos.", "success");
      setGlobalMessage("Escolha a prévia antes de publicar a música.", "success");
      await openPreviewEditor(uploadedTrack);
      await loadTracks();
      if (window.lucide) window.lucide.createIcons();
    } catch (error) {
      setMessage(message, error.message || "Não foi possível enviar a multitrack.", "error");
    } finally {
      button.disabled = false;
      button.querySelector("span").textContent = "Salvar e enviar multitrack";
    }
  });


  function previewTime(seconds) {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    return Math.floor(value / 60) + ":" + String(value % 60).padStart(2, "0");
  }

  async function openPreviewEditor(track) {
    const editor = $("previewEditor");
    const audio = $("previewSourceAudio");
    pendingPreviewTrack = track;
    $("previewTrackName").textContent = track.title || "Prévia da música";
    setMessage($("previewMessage"), "Mixando todos os instrumentos para você ouvir a música completa...");
    editor.hidden = false;
    editor.scrollIntoView({ behavior: "smooth", block: "center" });
    const token = sessionStorage.getItem(TOKEN_KEY) || "";
    const response = await fetch(API_BASE + "/developer/tracks/" + track.id + "/preview-source", {
      headers: token ? { Authorization: "Bearer " + token } : {}
    });
    if (!response.ok) throw new Error("Não foi possível abrir o áudio para selecionar a prévia.");
    const blob = await response.blob();
    if (previewSourceObjectUrl) URL.revokeObjectURL(previewSourceObjectUrl);
    previewSourceObjectUrl = URL.createObjectURL(blob);
    audio.src = previewSourceObjectUrl;
    audio.load();
  }

  $("previewSourceAudio").addEventListener("loadedmetadata", () => {
    const audio = $("previewSourceAudio");
    const validDuration = Number.isFinite(audio.duration) && audio.duration >= 30;
    const maxStart = validDuration ? Math.floor(audio.duration - 30) : 0;
    $("previewStartRange").max = String(maxStart);
    $("previewStartRange").disabled = !validDuration;
    $("savePreviewButton").disabled = !validDuration;
    $("previewStartRange").value = "0";
    previewStart = 0;
    $("previewStartLabel").textContent = "0:00";
    $("previewEndLabel").textContent = "0:30";
    setMessage($("previewMessage"), !validDuration ? "A mixagem precisa ter pelo menos 30 segundos." : "Todas as faixas estão sincronizadas na mixagem. Arraste o seletor e aperte play para escolher o trecho.", !validDuration ? "error" : "success");
  });
  $("previewSourceAudio").addEventListener("error", () => {
    $("savePreviewButton").disabled = true;
    setMessage($("previewMessage"), "Não foi possível ler o áudio-base. Confira o ZIP e tente abrir o editor novamente.", "error");
  });

  $("previewStartRange").addEventListener("input", () => {
    previewStart = Number($("previewStartRange").value);
    $("previewStartLabel").textContent = previewTime(previewStart);
    $("previewEndLabel").textContent = previewTime(previewStart + 30);
    $("previewSourceAudio").currentTime = previewStart;
  });
  $("previewSourceAudio").addEventListener("play", () => {
    const audio = $("previewSourceAudio");
    if (audio.currentTime < previewStart || audio.currentTime >= previewStart + 30) audio.currentTime = previewStart;
  });
  $("previewSourceAudio").addEventListener("timeupdate", () => {
    const audio = $("previewSourceAudio");
    if (!audio.paused && audio.currentTime >= previewStart + 30) {
      audio.pause();
      audio.currentTime = previewStart;
    }
  });
  $("previewPublishToggle").addEventListener("change", () => {
    previewPublishAfter = $("previewPublishToggle").checked;
  });

  $("savePreviewButton").addEventListener("click", async () => {
    if (!pendingPreviewTrack) return;
    const button = $("savePreviewButton");
    button.disabled = true;
    button.querySelector("span").textContent = "Gerando prévias...";
    setMessage($("previewMessage"), "O servidor está preparando os arquivos leves de 30 segundos. Aguarde.");
    const body = new FormData();
    body.set("start_seconds", String(previewStart));
    body.set("publish_after", previewPublishAfter ? "true" : "false");
    try {
      await request("/developer/tracks/" + pendingPreviewTrack.id + "/preview", { method: "POST", body });
      $("previewSourceAudio").pause();
      $("previewSourceAudio").removeAttribute("src");
      $("previewSourceAudio").load();
      if (previewSourceObjectUrl) URL.revokeObjectURL(previewSourceObjectUrl);
      previewSourceObjectUrl = null;
      $("previewEditor").hidden = true;
      pendingPreviewTrack = null;
      setGlobalMessage("Prévia de 30 segundos gerada e música preparada.", "success");
      await loadTracks();
    } catch (error) {
      setMessage($("previewMessage"), error.message || "Não foi possível gerar as prévias.", "error");
    } finally {
      button.disabled = false;
      button.querySelector("span").textContent = "Gerar prévias e concluir";
    }
  });

  $("tracksTable").addEventListener("click", async event => {
    const deleteButton = event.target.closest("[data-track-delete]");
    if (deleteButton) {
      const trackId = deleteButton.dataset.trackDelete;
      const row = deleteButton.closest("tr");
      const trackTitle = row?.querySelector(".cell-primary")?.textContent?.trim() || "esta track";
      if (!window.confirm('Excluir "' + trackTitle + '" permanentemente? Os arquivos enviados também serão apagados. Esta ação não pode ser desfeita.')) return;
      deleteButton.disabled = true;
      try {
        await request("/developer/tracks/" + trackId, { method: "DELETE" });
        if (pendingPreviewTrack && String(pendingPreviewTrack.id) === String(trackId)) {
          $("previewSourceAudio").pause();
          $("previewSourceAudio").removeAttribute("src");
          $("previewSourceAudio").load();
          if (previewSourceObjectUrl) URL.revokeObjectURL(previewSourceObjectUrl);
          previewSourceObjectUrl = null;
          pendingPreviewTrack = null;
          $("previewEditor").hidden = true;
        }
        setGlobalMessage("Track excluída e removida do catálogo.", "success");
        await loadTracks();
      } catch (error) {
        setGlobalMessage(error.message || "Não foi possível excluir a track.", "error");
        deleteButton.disabled = false;
      }
      return;
    }

    const previewButton = event.target.closest("[data-track-preview]");
    if (previewButton) {
      previewButton.disabled = true;
      try {
        const data = await request("/developer/tracks");
        const track = (data.items || []).find(item => String(item.id) === previewButton.dataset.trackPreview);
        if (!track) throw new Error("Multitrack não encontrada na biblioteca.");
        previewPublishAfter = Boolean(track.is_published);
        $("previewPublishToggle").checked = previewPublishAfter;
        await openPreviewEditor(track);
      } catch (error) {
        setGlobalMessage(error.message || "Não foi possível abrir o editor da prévia.", "error");
      } finally {
        previewButton.disabled = false;
      }
      return;
    }
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