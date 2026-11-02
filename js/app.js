const tracks = [
            { id: 1, title: "Ousado Amor", artist: "SONARA Sessions", key: "G", bpm: 68, genre: "Worship", cover: "cover-one" },
            { id: 2, title: "A Casa É Sua", artist: "SONARA Sessions", key: "D", bpm: 72, genre: "Worship", cover: "cover-two" },
            { id: 3, title: "Lugar Secreto", artist: "SONARA Sessions", key: "F#m", bpm: 75, genre: "Adoração", cover: "cover-three" },
            { id: 4, title: "Bondade de Deus", artist: "SONARA Sessions", key: "G", bpm: 70, genre: "Worship", cover: "cover-four" }
        ];

        // Conteúdo fictício exclusivamente para demonstração visual.
        let favorites = new Set();
        let currentTrack = null;
        let playing = false;
        let searchTerm = "";

        function renderCards(target, items) {
            const container = document.getElementById(target);
            if (!container) return;

            container.innerHTML = items.map(track => `
    <article class="music-card" onclick="selectTrack(${track.id})">
      <div class="cover ${track.cover}">
        <i data-lucide="audio-lines" class="cover-icon"></i>
        <button class="cover-play" aria-label="Reproduzir ${track.title}" onclick="event.stopPropagation();selectTrack(${track.id})">
          <i data-lucide="play" size="18"></i>
        </button>
      </div>
      <h3>${track.title}</h3>
      <p>${track.artist} · ${track.genre}</p>
      <button class="icon-button" style="margin-top:9px" aria-label="Favoritar ${track.title}" onclick="event.stopPropagation();toggleFavorite(${track.id})">
        <i data-lucide="${favorites.has(track.id) ? 'heart' : 'heart'}" size="16" style="color:${favorites.has(track.id) ? '#F06A78' : '#747F95'}"></i>
      </button>
    </article>
  `).join("");

            lucide.createIcons();
        }

        function renderAll() {
            const filtered = tracks.filter(t =>
                `${t.title} ${t.artist} ${t.key} ${t.bpm} ${t.genre}`
                    .toLowerCase().includes(searchTerm.toLowerCase())
            );

            renderCards("musicGrid", filtered);
            renderCards("exploreGrid", filtered);
            renderCards("libraryGrid", tracks);
            renderCards("favoritesGrid", tracks.filter(t => favorites.has(t.id)));

            document.getElementById("emptyState").style.display =
                filtered.length ? "none" : "block";

            document.getElementById("recentTracks").innerHTML = filtered.map(t => `
    <tr>
      <td class="track-name">
        <div class="mini-cover"><i data-lucide="audio-lines" size="17"></i></div>
        <span>${t.title}</span>
      </td>
      <td>${t.key}</td>
      <td>${t.bpm}</td>
      <td><span class="badge">DEMO</span></td>
    </tr>
  `).join("");

            lucide.createIcons();
        }

        function navigate(page) {
            document.querySelectorAll(".page").forEach(el => el.classList.remove("active"));
            document.querySelectorAll("[data-page]").forEach(el => el.classList.remove("active"));

            document.getElementById("page-" + page)?.classList.add("active");

            document.querySelectorAll(`[data-page="${page}"]`).forEach(el => el.classList.add("active"));

            window.scrollTo({ top: 0, behavior: "smooth" });
        }

        document.querySelectorAll("[data-page]").forEach(button => {
            button.addEventListener("click", () => navigate(button.dataset.page));
        });

        function selectTrack(id) {
            currentTrack = tracks.find(t => t.id === id);
            if (!currentTrack) return;

            document.getElementById("playerTitle").textContent = currentTrack.title;
            document.getElementById("playerArtist").textContent = currentTrack.artist;

            showToast("Música selecionada. Arquivo de áudio ainda não cadastrado.");
            lucide.createIcons();
        }

        function togglePlay() {
            if (!currentTrack) {
                showToast("Selecione uma música primeiro.");
                return;
            }

            showToast("Player visual: aguardando integração com arquivos de áudio.");
        }

        function toggleFavorite(id) {
            if (favorites.has(id)) favorites.delete(id);
            else favorites.add(id);

            renderAll();
            showToast(favorites.has(id) ? "Adicionada aos favoritos." : "Removida dos favoritos.");
        }

        function showToast(message) {
            const toast = document.getElementById("toast");
            toast.textContent = message;
            toast.classList.add("show");
            clearTimeout(window.toastTimer);
            window.toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
        }

        document.getElementById("searchInput").addEventListener("input", e => {
            searchTerm = e.target.value;
            renderAll();
        });

        document.addEventListener("keydown", e => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
                e.preventDefault();
                document.getElementById("searchInput").focus();
            }
        });

        const wave = document.getElementById("heroWave");
        const heights = [25, 42, 65, 95, 70, 115, 85, 55, 100, 125, 75, 45, 95, 115, 70, 38, 85, 105, 55, 35, 75, 95, 50, 25];

        wave.innerHTML = heights.map((h, i) =>
            `<span style="height:${h}px;animation-delay:${i * .07}s"></span>`
        ).join("");

        renderAll();
        lucide.createIcons();

/* SONARA user authentication */
const SONARA_API_BASE = "http://127.0.0.1:8000/api/v1";
const SONARA_USER_TOKEN = "sonaraUserAccessToken";
let sonaraCurrentUser = null;
let authMode = "login";

function setAuthMode(mode) {
    authMode = mode;
    const registering = mode === "register";
    document.getElementById("authTitle").textContent = registering ? "Crie sua conta" : "Entre na sua conta";
    document.getElementById("authDescription").textContent = registering
        ? "Crie seu acesso para começar a organizar sua experiência musical."
        : "Acesse sua biblioteca e organize sua jornada musical.";
    document.querySelectorAll("[data-auth-mode]").forEach(button =>
        button.classList.toggle("active", button.dataset.authMode === mode)
    );
    document.querySelectorAll(".auth-name-field").forEach(field => field.hidden = !registering);
    document.getElementById("authPassword").autocomplete = registering ? "new-password" : "current-password";
    document.getElementById("authSubmit").innerHTML = registering
        ? 'Criar minha conta <i data-lucide="arrow-right"></i>'
        : 'Entrar <i data-lucide="arrow-right"></i>';
    document.getElementById("authMessage").textContent = "";
    lucide.createIcons();
}

function openAuthModal() {
    const overlay = document.getElementById("authOverlay");
    overlay.classList.add("active");
    overlay.setAttribute("aria-hidden", "false");
    const form = document.getElementById("userAuthForm");
    const account = document.getElementById("authAccount");
    if (sonaraCurrentUser) {
        form.hidden = true;
        document.getElementById("authTabs").hidden = true;
        account.hidden = false;
        document.getElementById("authTitle").textContent = "Sua conta SONARA";
        document.getElementById("authDescription").textContent = "Sua sessão está ativa.";
        document.getElementById("authAccountName").textContent = sonaraCurrentUser.full_name;
        document.getElementById("authAccountEmail").textContent = sonaraCurrentUser.email;
    } else {
        form.hidden = false;
        document.getElementById("authTabs").hidden = false;
        account.hidden = true;
        setAuthMode("login");
    }
    lucide.createIcons();
}

function closeAuthModal() {
    const overlay = document.getElementById("authOverlay");
    overlay.classList.remove("active");
    overlay.setAttribute("aria-hidden", "true");
}

async function sonaraApi(path, options = {}, token = "") {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (token) headers.Authorization = "Bearer " + token;
    const response = await fetch(SONARA_API_BASE + path, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(data.detail || "Não foi possível concluir a operação.");
        error.status = response.status;
        throw error;
    }
    return data;
}

async function restoreSonaraUserSession() {
    const token = sessionStorage.getItem(SONARA_USER_TOKEN);
    if (!token) return;
    try {
        sonaraCurrentUser = await sonaraApi("/auth/me", { method: "GET" }, token);
        const avatar = document.getElementById("userAccountButton");
        avatar.textContent = (sonaraCurrentUser.full_name || "S").trim().charAt(0).toUpperCase();
        avatar.setAttribute("aria-label", "Conta de " + sonaraCurrentUser.full_name);
    } catch {
        sessionStorage.removeItem(SONARA_USER_TOKEN);
        sonaraCurrentUser = null;
    }
}

document.getElementById("userAccountButton").addEventListener("click", openAuthModal);
document.getElementById("authClose").addEventListener("click", closeAuthModal);
document.getElementById("authOverlay").addEventListener("click", event => {
    if (event.target.id === "authOverlay") closeAuthModal();
});
document.querySelectorAll("[data-auth-mode]").forEach(button =>
    button.addEventListener("click", () => setAuthMode(button.dataset.authMode))
);
document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeAuthModal();
});

document.getElementById("userAuthForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = document.getElementById("authSubmit");
    const message = document.getElementById("authMessage");
    const email = document.getElementById("authEmail").value.trim();
    const password = document.getElementById("authPassword").value;
    const fullName = document.getElementById("authName").value.trim();
    button.disabled = true;
    message.textContent = "";
    try {
        if (authMode === "register") {
            await sonaraApi("/auth/register", {
                method: "POST",
                body: JSON.stringify({ email, full_name: fullName, password })
            });
        }
        const tokenResult = await sonaraApi("/auth/login", {
            method: "POST",
            body: JSON.stringify({ email, password })
        });
        sessionStorage.setItem(SONARA_USER_TOKEN, tokenResult.access_token);
        sonaraCurrentUser = await sonaraApi("/auth/me", { method: "GET" }, tokenResult.access_token);
        document.getElementById("userAccountButton").textContent =
            sonaraCurrentUser.full_name.trim().charAt(0).toUpperCase();
        document.getElementById("userAuthForm").reset();
        openAuthModal();
        showToast(authMode === "register" ? "Conta criada com sucesso!" : "Login realizado com sucesso!");
    } catch (error) {
        if (error instanceof TypeError) {
            message.textContent = "Não foi possível conectar à SONARA. Verifique se o backend está iniciado.";
        } else if (error.status === 409) {
            message.textContent = "Este e-mail já possui uma conta. Tente entrar.";
        } else if (error.status === 401) {
            message.textContent = "E-mail ou senha inválidos.";
        } else {
            message.textContent = error.message;
        }
    } finally {
        button.disabled = false;
    }
});

document.getElementById("authLogout").addEventListener("click", () => {
    sessionStorage.removeItem(SONARA_USER_TOKEN);
    sonaraCurrentUser = null;
    document.getElementById("userAccountButton").textContent = "S";
    document.getElementById("userAccountButton").setAttribute("aria-label", "Entrar ou acessar minha conta");
    closeAuthModal();
    showToast("Você saiu da sua conta.");
});

restoreSonaraUserSession();
