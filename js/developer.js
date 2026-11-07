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
  const driveCallbackState = new URLSearchParams(window.location.search).get("drive");
  let identity = null;
  let userQuery = "";
  let refreshInProgress = false;
  let pendingPreviewTrack = null;
  let previewPublishAfter = false;
  let previewSourceObjectUrl = null;
  let previewStart = 0;
  let previewEnd = 30;
  let previewSourceDuration = 0;

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
    const developerIdentity = $("developerIdentity");
    if (developerIdentity) developerIdentity.textContent = identity?.name || identity?.email || "Sessão administrativa validada.";
    $("sidebarIdentity").textContent = identity?.email || "Sessão validada";
    if (window.lucide) window.lucide.createIcons();
    if (driveCallbackState === "connected" || driveCallbackState === "error") {
      setActiveTab("drive");
    }
    loadDriveStatus().finally(() => {
      if (driveCallbackState === "error") {
        setMessage($("driveStatusMessage"), "O Google retornou um erro na autorização. Confira o log do backend para identificar a causa.", "error");
      }
    });
    if (driveCallbackState === "connected") {
      window.history.replaceState({}, "", window.location.pathname);
    }
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
      drive: ["Importação pelo Google Drive", "Conecte seu Google Drive e importe pastas de multitracks em lote."],
      revenue: ["Receitas", "Acompanhe os lançamentos financeiros registrados."]
    };
    $("pageTitle").textContent = labels[tab][0];
    $("pageIntro").textContent = labels[tab][1];
    if (window.lucide) window.lucide.createIcons();
  }

  async function loadUsers() {
    const params = new URLSearchParams({ q: userQuery, limit: "200" });
    const data = await request("/developer/users?" + params.toString());
    $("overviewUsers").textContent = Number(data.total ?? data.items.length).toLocaleString("pt-BR");
    $("navUserCount").textContent = data.total ?? data.items.length;
    $("usersCount").textContent = (data.total ?? data.items.length) + " usuário(s) encontrado(s).";
    const rows = data.items.map(user => `
      <tr>
        <td><div class="cell-primary">${escapeHtml(user.full_name)}</div><div class="cell-secondary">${escapeHtml(user.email)}</div></td>
        <td>${escapeHtml(formatDate(user.created_at))}</td>
        <td><span class="status-pill ${user.is_active ? "active" : "inactive"}">${user.is_active ? "Ativo" : "Desativado"}</span></td>
        <td><div class="user-actions"><button class="table-action" data-user-status="${user.id}" data-next-active="${user.is_active ? "false" : "true"}">${user.is_active ? "Desativar" : "Reativar"}</button><button class="table-action danger" data-user-delete="${user.id}" data-user-name="${escapeHtml(user.full_name)}">Excluir</button></div></td>
      </tr>`).join("");
    $("usersTable").innerHTML = rows || '<tr><td colspan="4" class="empty-cell">Nenhum usuário encontrado.</td></tr>';
  }

  async function loadTracks() {
    const results = await Promise.all([request("/developer/tracks"), request("/developer/track-categories")]);
    const tracks = results[0].items || [];
    renderCategoryOptions(results[1].items || []);
    const published = tracks.filter(track => track.is_published).length;
    $("overviewTracks").textContent = published.toLocaleString("pt-BR");
    const rows = tracks.map(track => {
      const tags = (track.categories || []).map(tag => '<span class="tag-pill">' + escapeHtml(tag) + '</span>').join(" ");
      return '<tr>' +
        '<td><div class="cell-primary">' + escapeHtml(track.title) + '</div><div class="cell-secondary">' + escapeHtml(track.artist || "Artista não informado") + '</div></td>' +
        '<td>' + escapeHtml(track.musical_key || "Tom —") + ' · ' + (track.bpm ? escapeHtml(track.bpm + " BPM") : "BPM —") + '<div class="cell-secondary">' + escapeHtml(track.time_signature || "4/4") + '</div></td>' +
        '<td><div class="tag-list">' + (tags || "—") + '</div></td>' +
        '<td>' + (track.stems || []).length + ' arquivo(s)<div class="cell-secondary">' + escapeHtml(track.original_filename) + '</div></td>' +
        '<td><span class="status-pill ' + (track.is_published ? "published" : "unpublished") + '">' + (track.is_published ? "Publicada" : "Rascunho") + '</span><div class="cell-secondary">' + (track.preview_ready ? "Prévia de 30s pronta" : "Prévia ainda não configurada") + '</div></td>' +
        '<td>' +
          '<button class="table-action" data-track-edit="' + track.id + '">Editar nome/capa</button> ' +
          '<button class="table-action" data-track-preview="' + track.id + '"> ' + (track.preview_ready ? "Editar prévia" : "Configurar prévia") + '</button> ' +
          (track.preview_ready ? '<button class="table-action" data-track-publish="' + track.id + '" data-next-published="' + (track.is_published ? "false" : "true") + '">' + (track.is_published ? "Retirar do site" : "Publicar") + '</button>' : '') +
          '<button class="table-action danger" data-track-delete="' + track.id + '">Excluir track</button>' +
        '</td></tr>';
    }).join("");
    $("tracksTable").innerHTML = rows || '<tr><td colspan="6" class="empty-cell">Nenhuma track enviada ainda.</td></tr>';
    return tracks;
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
    $("overviewRevenue").textContent = formatMoney(summary.received_total);
    $("revenueReceived").textContent = formatMoney(summary.received_total);
    $("revenuePending").textContent = formatMoney(summary.pending_total);
    $("revenueEntries").textContent = summary.entries_count ?? (data.items || []).length;
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


  let homepageFeatureTracks = [];
  let homepageFeatureSelection = { launches: [], most_downloaded: [] };

  function renderHomepageFeatureOptions() {
    const renderGroup = (targetId, key, limit) => {
      const container = $(targetId);
      const selected = new Set(homepageFeatureSelection[key].map(Number));
      container.innerHTML = homepageFeatureTracks.map(track => {
        const id = Number(track.id);
        return '<label class="homepage-feature-option"><input type="checkbox" data-home-feature="' + key + '" value="' + id + '" ' + (selected.has(id) ? "checked" : "") + '><span>' + escapeHtml(track.title) + '<small>' + escapeHtml(track.artist || "Artista não informado") + '</small></span></label>';
      }).join("") || '<span class="muted">Nenhuma track publicada disponível.</span>';
      container.querySelectorAll("input").forEach(input => input.addEventListener("change", () => {
        const checked = [...container.querySelectorAll("input:checked")];
        if (checked.length > limit) {
          input.checked = false;
          setMessage($("homepageFeatureMessage"), "Selecione no máximo " + limit + " tracks nesta seção.", "error");
          return;
        }
        homepageFeatureSelection[key] = checked.map(item => Number(item.value));
        setMessage($("homepageFeatureMessage"), "");
      }));
    };
    renderGroup("launchesFeatureOptions", "launches", 12);
    renderGroup("mostDownloadedFeatureOptions", "most_downloaded", 14);
  }

  async function loadHomepageFeatures() {
    const [tracksData, selection] = await Promise.all([
      request("/developer/tracks"),
      request("/developer/homepage-features")
    ]);
    homepageFeatureTracks = (tracksData.items || []).filter(track => track.is_published && track.cover_url);
    homepageFeatureSelection = {
      launches: selection.launches || [],
      most_downloaded: selection.most_downloaded || []
    };
    renderHomepageFeatureOptions();
  }

  async function saveHomepageFeatures() {
    const button = $("saveHomepageFeatures");
    button.disabled = true;
    try {
      const saved = await request("/developer/homepage-features", {
        method: "PUT",
        body: JSON.stringify(homepageFeatureSelection)
      });
      homepageFeatureSelection = { launches: saved.launches, most_downloaded: saved.most_downloaded };
      setMessage($("homepageFeatureMessage"), "Destaques salvos com sucesso.", "success");
    } catch (error) {
      setMessage($("homepageFeatureMessage"), error.message || "Não foi possível salvar os destaques.", "error");
    } finally {
      button.disabled = false;
    }
  }


  async function refreshAll() {
    if (refreshInProgress) return;
    refreshInProgress = true;
    $("refreshButton").disabled = true;
    setGlobalMessage("Atualizando dados...");
    const results = await Promise.allSettled([loadUsers(), loadTracks(), loadRevenue(), loadHomepageFeatures()]);
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
    if (!token) {
      showLogin();
      return;
    }

    try {
      identity = await request("/developer/me", { method: "GET" }, token);
      showDashboard(identity);
      await refreshAll();
    } catch (error) {
      // Só encerra a sessão quando a API confirma que o token não é mais válido.
      // Falhas de rede, indisponibilidade ou erros 5xx não podem expulsar o admin.
      if (error.status === 401 || error.status === 403) {
        sessionStorage.removeItem(TOKEN_KEY);
        showLogin();
        setMessage(loginMessage, "Sua sessão administrativa expirou. Entre novamente.", "error");
        return;
      }

      showDashboard(identity || { name: "Sessão administrativa", email: "Conexão temporariamente indisponível" });
      setGlobalMessage(
        "Não foi possível validar a sessão agora. Seu acesso foi preservado; verifique o backend e tente atualizar os dados. " +
        (error.message || ""),
        "error"
      );
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
  $("saveHomepageFeatures").addEventListener("click", saveHomepageFeatures);
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
    const deleteButton = event.target.closest("[data-user-delete]");
    if (deleteButton) {
      const userId = deleteButton.dataset.userDelete;
      const userName = deleteButton.dataset.userName || "este usuário";
      if (!window.confirm('Excluir permanentemente a conta de "' + userName + '"? Os dados da conta serão apagados e esta ação não pode ser desfeita.')) return;
      deleteButton.disabled = true;
      try {
        await request("/developer/users/" + userId, { method: "DELETE" });
        setGlobalMessage("Usuário e dados da conta excluídos permanentemente.", "success");
        await loadUsers();
      } catch (error) {
        setGlobalMessage(error.message || "Não foi possível excluir o usuário.", "error");
        deleteButton.disabled = false;
      }
      return;
    }

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

  function updatePreviewSelection(seekToStart = false) {
    $("previewStartLabel").textContent = previewTime(previewStart);
    $("previewEndLabel").textContent = previewTime(previewEnd);
    $("previewWindowLabel").textContent = "PRÉVIA · " + previewTime(previewEnd - previewStart);
    $("previewEndRange").min = String(previewStart + 1);
    $("previewEndRange").max = String(Math.min(previewSourceDuration, previewStart + 30));
    $("previewEndRange").value = String(previewEnd);
    if (seekToStart) $("previewSourceAudio").currentTime = previewStart;
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
    if (!response.ok) {
      let detail = "Não foi possível gerar a mixagem de referência.";
      try { const payload = await response.json(); detail = payload.detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    const blob = await response.blob();
    if (!blob.size || !blob.type.startsWith("audio/")) throw new Error("O servidor não retornou um arquivo de áudio válido para a mixagem.");
    if (previewSourceObjectUrl) URL.revokeObjectURL(previewSourceObjectUrl);
    previewSourceObjectUrl = URL.createObjectURL(blob);
    audio.src = previewSourceObjectUrl;
    audio.load();
  }

  async function openTrackMetadataEditor(track) {
    $("trackMetadataEditor").hidden = false;
    $("editTrackTitle").value = track.title || "";
    $("editTrackArtist").value = track.artist || "";
    $("editTrackCover").value = "";
    $("trackMetadataForm").dataset.trackId = String(track.id);
    setMessage($("trackMetadataMessage"), "Edite o nome e, se desejar, escolha uma nova capa. Os stems importados serão mantidos.");
    $("trackMetadataEditor").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  $("cancelTrackMetadata").addEventListener("click", () => {
    $("trackMetadataEditor").hidden = true;
    $("trackMetadataForm").reset();
  });

  $("trackMetadataForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const trackId = form.dataset.trackId;
    if (!trackId) return;
    const button = $("saveTrackMetadata");
    const body = new FormData();
    body.set("title", $("editTrackTitle").value.trim());
    body.set("artist", $("editTrackArtist").value.trim());
    const cover = $("editTrackCover").files[0];
    if (cover) body.set("cover", cover);
    button.disabled = true;
    setMessage($("trackMetadataMessage"), "Salvando informações da música...");
    try {
      await request("/developer/tracks/" + trackId, { method: "PATCH", body });
      setMessage($("trackMetadataMessage"), "Nome e capa salvos com sucesso.", "success");
      await loadTracks();
      $("trackMetadataEditor").hidden = true;
      const refreshed = await request("/developer/tracks");
      const savedTrack = (refreshed.items || []).find(track => String(track.id) === String(trackId));
      if (savedTrack) {
        previewPublishAfter = Boolean(savedTrack.is_published);
        $("previewPublishToggle").checked = previewPublishAfter;
        await openPreviewEditor(savedTrack);
        setGlobalMessage("Nome e capa salvos. Agora escolha o trecho de áudio da prévia.", "success");
      } else {
        setGlobalMessage("Informações salvas. Abra a configuração de prévia na lista de tracks.", "success");
      }
    } catch (error) {
      setMessage($("trackMetadataMessage"), error.message || "Não foi possível salvar os dados da música.", "error");
    } finally {
      button.disabled = false;
    }
  });

  $("previewSourceAudio").addEventListener("loadedmetadata", () => {
    const audio = $("previewSourceAudio");
    previewSourceDuration = Number.isFinite(audio.duration) ? Math.floor(audio.duration) : 0;
    const validDuration = previewSourceDuration >= 2;
    previewStart = 0;
    previewEnd = Math.min(30, previewSourceDuration);
    $("previewStartRange").max = String(Math.max(0, previewSourceDuration - 1));
    $("previewStartRange").value = "0";
    $("previewStartRange").disabled = !validDuration;
    $("previewEndRange").disabled = !validDuration;
    $("savePreviewButton").disabled = !validDuration;
    updatePreviewSelection();
    setMessage($("previewMessage"), !validDuration
      ? "A mixagem precisa ter pelo menos 2 segundos."
      : "Arraste os controles de início e fim. Você pode selecionar qualquer trecho de até 30 segundos.",
      !validDuration ? "error" : "success");
  });
  $("previewSourceAudio").addEventListener("error", () => {
    $("savePreviewButton").disabled = true;
    setMessage($("previewMessage"), "Não foi possível ler o áudio-base. Confira o ZIP e tente abrir o editor novamente.", "error");
  });

  $("previewStartRange").addEventListener("input", () => {
    previewStart = Number($("previewStartRange").value);
    if (previewEnd <= previewStart) previewEnd = previewStart + 1;
    if (previewEnd > previewStart + 30) previewEnd = previewStart + 30;
    updatePreviewSelection(true);
  });
  $("previewEndRange").addEventListener("input", () => {
    previewEnd = Number($("previewEndRange").value);
    updatePreviewSelection();
  });
  $("previewSourceAudio").addEventListener("play", () => {
    const audio = $("previewSourceAudio");
    if (audio.currentTime < previewStart || audio.currentTime >= previewEnd) audio.currentTime = previewStart;
  });
  $("previewSourceAudio").addEventListener("timeupdate", () => {
    const audio = $("previewSourceAudio");
    if (!audio.paused && audio.currentTime >= previewEnd) {
      audio.pause();
      audio.currentTime = previewStart;
    }
  });
  $("previewPublishToggle").addEventListener("change", () => {
    previewPublishAfter = $("previewPublishToggle").checked;
  });

  $("savePreviewButton").addEventListener("click", async () => {
    if (!pendingPreviewTrack) return;
    const duration = previewEnd - previewStart;
    if (duration < 1 || duration > 30) {
      setMessage($("previewMessage"), "Escolha um intervalo entre 1 e 30 segundos.", "error");
      return;
    }
    const button = $("savePreviewButton");
    button.disabled = true;
    button.querySelector("span").textContent = "Gerando prévias...";
    setMessage($("previewMessage"), "Gerando os trechos selecionados para todos os instrumentos. Aguarde.");
    const body = new FormData();
    body.set("start_seconds", String(previewStart));
    body.set("end_seconds", String(previewEnd));
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
      setGlobalMessage("Prévia selecionada gerada e música preparada para publicação.", "success");
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

    const editButton = event.target.closest("[data-track-edit]");
    if (editButton) {
      editButton.disabled = true;
      try {
        const data = await request("/developer/tracks");
        const track = (data.items || []).find(item => String(item.id) === editButton.dataset.trackEdit);
        if (!track) throw new Error("Multitrack não encontrada na biblioteca.");
        await openTrackMetadataEditor(track);
      } catch (error) {
        setGlobalMessage(error.message || "Não foi possível abrir a edição da música.", "error");
      } finally {
        editButton.disabled = false;
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


  function extractDriveFolderId(value) {
    const input = String(value || "").trim();
    const match = input.match(/(?:folders\/|[?&]id=)([A-Za-z0-9_-]+)/);
    return match ? match[1] : (/^[A-Za-z0-9_-]{10,}$/.test(input) ? input : "");
  }

  async function loadDriveStatus() {
    try {
      const status = await request("/developer/drive/status");
      const message = $("driveStatusMessage");
      if (!status.configured) {
        setMessage(message, "Integração criada. Falta configurar as credenciais OAuth do Google no backend.", "error");
      } else if (status.connected) {
        setMessage(message, "Google Drive conectado" + (status.email ? " (" + status.email + ")" : "") + ".", "success");
      } else {
        setMessage(message, "Credenciais configuradas. Conecte sua conta Google para continuar.");
      }
      $("driveConnectButton").textContent = status.connected ? "Google Drive conectado" : "Vincular Google Drive";
      $("openDriveTab").querySelector("span").textContent = status.connected ? "Google Drive conectado" : "Vincular Google Drive";
      $("connectDriveSidebarButton").innerHTML = status.connected
        ? '<i data-lucide="cloud-check"></i> Google Drive conectado'
        : '<i data-lucide="cloud-upload"></i> Vincular Google Drive';
      $("driveDisconnectButton").hidden = !status.connected;
      if (window.lucide) window.lucide.createIcons();
      $("driveScanButton").disabled = !status.connected;
    } catch (error) {
      setMessage($("driveStatusMessage"), error.message, "error");
    }
  }

  async function beginDriveConnection() {
    setActiveTab("drive");
    const buttons = [$("driveConnectButton"), $("openDriveTab"), $("connectDriveSidebarButton")];
    buttons.forEach(button => { if (button) button.disabled = true; });
    setMessage($("driveStatusMessage"), "Abrindo a autorização segura do Google Drive...");
    try {
      const result = await request("/developer/drive/connect");
      if (!result.authorization_url) throw new Error("O servidor não retornou o link de autorização do Google.");
      window.location.assign(result.authorization_url);
    } catch (error) {
      setMessage($("driveStatusMessage"), error.message || "Não foi possível iniciar a conexão com o Google Drive.", "error");
      buttons.forEach(button => { if (button) button.disabled = false; });
    }
  }

  $("driveConnectButton").addEventListener("click", beginDriveConnection);
  $("openDriveTab").addEventListener("click", beginDriveConnection);
  $("connectDriveSidebarButton").addEventListener("click", beginDriveConnection);

  $("driveDisconnectButton").addEventListener("click", async () => {
    try {
      await request("/developer/drive/connection", { method: "DELETE" });
      $("driveFolderResults").innerHTML = "";
      setMessage($("driveStatusMessage"), "Google Drive desconectado.");
      await loadDriveStatus();
    } catch (error) {
      setMessage($("driveStatusMessage"), error.message, "error");
    }
  });

  $("driveScanButton").addEventListener("click", async () => {
    const folderId = extractDriveFolderId($("driveRootFolder").value);
    if (!folderId) {
      setMessage($("driveStatusMessage"), "Cole o link ou ID de uma pasta válida do Google Drive.", "error");
      return;
    }
    const button = $("driveScanButton");
    button.disabled = true;
    $("driveFolderResults").innerHTML = "";
    try {
      const result = await request("/developer/drive/folders?parent_id=" + encodeURIComponent(folderId));
      $("driveFolderResults").innerHTML = (result.folders || []).map(folder => {
        const isZip = folder.item_type === "zip";
        const disabled = folder.already_imported || (!isZip && !folder.audio_count);
        const detail = folder.already_imported ? "Já importada" :
          isZip ? "Arquivo ZIP · será extraído automaticamente" :
          folder.audio_count ? "Pronta para importar" : "Sem áudio compatível";
        return '<label class="check-field" style="padding:12px;border:1px solid rgba(148,163,184,.18);border-radius:10px;display:flex;gap:12px;align-items:center">' +
          '<input type="checkbox" data-drive-folder="' + escapeHtml(folder.id) + '" ' + (disabled ? "disabled" : "checked") + '>' +
          '<span style="display:grid;gap:3px"><strong>' + (isZip ? "🗜️ " : "📁 ") + escapeHtml(folder.name) + '</strong><small>' +
          (isZip ? "ZIP com extração automática" : folder.audio_count + " arquivo(s) de áudio") + ' · ' + detail +
          '</small></span></label>';
      }).join("") || '<p class="muted">Nenhuma pasta ou arquivo ZIP de música encontrado dentro da pasta selecionada.</p>';
      $("driveImportButton").disabled = !(result.folders || []).some(folder => !folder.already_imported && (folder.item_type === "zip" || folder.audio_count));
      setMessage($("driveStatusMessage"), result.total + " item(ns) encontrado(s) em “" + result.parent + "”. Selecione as músicas ou ZIPs que deseja importar.", "success");
    } catch (error) {
      setMessage($("driveStatusMessage"), error.message, "error");
    } finally {
      button.disabled = false;
    }
  });

  $("driveImportButton").addEventListener("click", async event => {
    // Impede qualquer submit/navegação acidental do formulário administrativo.
    event.preventDefault();
    event.stopPropagation();

    const folderIds = [...$("driveFolderResults").querySelectorAll("input[data-drive-folder]:checked")].map(input => input.dataset.driveFolder);
    if (!folderIds.length) {
      setMessage($("driveStatusMessage"), "Selecione pelo menos um arquivo ZIP ou uma pasta antes de importar.", "error");
      return;
    }

    const button = $("driveImportButton");
    const originalLabel = button.textContent;
    button.disabled = true;
    button.textContent = "Importando... aguarde";
    setMessage($("driveStatusMessage"), "A SONARA está copiando os arquivos para o armazenamento próprio. Não feche esta página.");

    try {
      const result = await request("/developer/drive/import", {
        method: "POST",
        body: JSON.stringify({ folder_ids: folderIds })
      });
      const imported = result.imported || [];
      const skipped = result.skipped || [];
      const errors = result.errors || [];
      let summary = imported.length + " multitrack(s) importada(s) como rascunho.";
      if (skipped.length) summary += " " + skipped.length + " já existia(m) e foi(ram) ignorada(s).";
      if (errors.length) summary += " " + errors.length + " item(ns) tiveram erro.";
      if (!imported.length && !skipped.length && !errors.length) {
        summary = "A importação terminou, mas o servidor não retornou itens processados.";
      }
      setMessage($("driveStatusMessage"), summary, errors.length ? "error" : "success");
      if (errors.length) {
        $("driveFolderResults").insertAdjacentHTML("beforeend",
          errors.map(item => '<p class="inline-message error">' + escapeHtml(item.message) + '</p>').join(""));
      }
      const trackToFinalize = imported[0] || skipped.find(item => item.id);

      // Troca diretamente para Tracks e faz uma única atualização da biblioteca.
      // Não executa refreshAll nem repete chamadas à API após a importação.
      setActiveTab("tracks");
      if (trackToFinalize) {
        const tracks = await loadTracks();
        const importedTrack = tracks.find(track => String(track.id) === String(trackToFinalize.id));
        if (importedTrack) {
          await openTrackMetadataEditor(importedTrack);
          setGlobalMessage(
            imported.length
              ? imported.length + " multitrack(s) importada(s) e carregada(s) em Tracks. Finalize nome e capa; depois escolha a prévia."
              : "Esta multitrack já estava importada. Você pode continuar a edição do nome, capa e prévia.",
            "success"
          );
        } else {
          setGlobalMessage("A importação foi concluída, mas a track não apareceu na consulta da biblioteca. Use Atualizar dados e confira o backend.", "error");
        }
      } else {
        // Mesmo em caso de erro parcial, mostra a biblioteca sem reiniciar a tela.
        await loadTracks();
      }
    } catch (error) {
      setMessage($("driveStatusMessage"), error.message || "Não foi possível importar os arquivos selecionados.", "error");
    } finally {
      button.disabled = false;
      button.textContent = originalLabel || "Importar músicas selecionadas";
    }
  });

  validateSession();
})();