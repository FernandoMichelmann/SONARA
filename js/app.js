let tracks = [];
        let homepageFeatureSelection = { launches: [], most_downloaded: [], configured: false };

        // Conteúdo fictício exclusivamente para demonstração visual.
        let favorites = new Set();
        let currentTrack = null;
        let playing = false;
        let stemPlayers = [];
        const audioPlayer = new Audio();
        const SONARA_CATALOG_API = "http://127.0.0.1:8000/api/v1";

        function escapeHTML(value) {
            return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
        }
        let searchTerm = "";

        function renderCards(target, items) {
            const container = document.getElementById(target);
            if (!container) return;

            container.innerHTML = items.map(track => `
    <article class="music-card" onclick="selectTrack(${track.id})">
      <div class="cover ${track.cover}">
        ${track.coverUrl ? '<img class="cover-art" src="' + escapeHTML(track.coverUrl) + '" alt="Capa de ' + escapeHTML(track.title) + '" loading="lazy">' : '<i data-lucide="audio-lines" class="cover-icon"></i>'}
        <button class="cover-play" aria-label="Reproduzir ${escapeHTML(track.title)}" onclick="event.stopPropagation();selectTrack(${track.id});togglePlay()">
          <i data-lucide="play" size="18"></i>
        </button>
      </div>
      <h3>${escapeHTML(track.title)}</h3>
      <p>${escapeHTML(track.artist)} · ${escapeHTML(track.genre)}</p>
      <button class="icon-button" style="margin-top:9px" aria-label="Favoritar ${track.title}" onclick="event.stopPropagation();toggleFavorite(${track.id})">
        <i data-lucide="${favorites.has(track.id) ? 'heart' : 'heart'}" size="16" style="color:${favorites.has(track.id) ? '#F06A78' : '#747F95'}"></i>
      </button>
    </article>
  `).join("");

            lucide.createIcons();
        }

        function renderFeaturedRails() {
            const featuredRail = document.getElementById("featuredRail");
            const originalsRail = document.getElementById("originalsRail");
            const available = tracks.filter(track => track.coverUrl);
            const byId = new Map(available.map(track => [Number(track.id), track]));
            const launches = homepageFeatureSelection.configured
                ? homepageFeatureSelection.launches.map(id => byId.get(Number(id))).filter(Boolean)
                : available.slice(0, 12);
            const mostDownloaded = homepageFeatureSelection.configured
                ? homepageFeatureSelection.most_downloaded.map(id => byId.get(Number(id))).filter(Boolean)
                : [...available].sort((a, b) => Number(b.download_count || 0) - Number(a.download_count || 0)).slice(0, 14);

            if (featuredRail) {
                featuredRail.innerHTML = launches.slice(0, 12).map(track => `
                    <button class="featured-tile" type="button" onclick="selectTrack(${track.id})" aria-label="Abrir ${escapeHTML(track.title)}">
                        <img src="${escapeHTML(track.coverUrl)}" alt="" loading="lazy">
                        <span class="featured-tile-shade"></span>
                        <span class="featured-tile-copy"><strong>${escapeHTML(track.title)}</strong><small>${escapeHTML(track.artist)}</small></span>
                    </button>
                `).join("") || '<div class="featured-empty">As novidades do catálogo aparecerão aqui.</div>';
            }

            if (originalsRail) {
                originalsRail.innerHTML = mostDownloaded.slice(0, 14).map((track, index) => `
                    <button class="original-poster" type="button" onclick="selectTrack(${track.id})" aria-label="Reproduzir ${escapeHTML(track.title)}">
                        <img src="${escapeHTML(track.coverUrl)}" alt="Capa de ${escapeHTML(track.title)}" loading="lazy">
                        <span class="poster-shade"></span>
                        <span class="poster-copy"><strong>${escapeHTML(track.title)}</strong><small>${escapeHTML(track.artist)}</small></span>
                        <span class="poster-number">${String(index + 1).padStart(2, "0")}</span>
                    </button>
                `).join("") || '<div class="featured-empty">Adicione capas aos lançamentos para montar esta seleção.</div>';
            }
        }

        function renderAll() {
            const filtered = tracks.filter(t =>
                `${t.title} ${t.artist} ${t.key} ${t.bpm} ${t.genre}`
                    .toLowerCase().includes(searchTerm.toLowerCase())
            );

            renderFeaturedRails();
            renderCards("musicGrid", filtered);
            renderCards("exploreGrid", filtered);
            renderCards("libraryGrid", tracks);
            renderCards("favoritesGrid", tracks.filter(t => favorites.has(t.id)));

            document.getElementById("emptyState").style.display =
                filtered.length ? "none" : "block";

            lucide.createIcons();
        }

        function navigate(page) {
            document.querySelectorAll(".page").forEach(el => el.classList.remove("active"));
            document.querySelectorAll("[data-page]").forEach(el => el.classList.remove("active"));

            document.getElementById("page-" + page)?.classList.add("active");

            document.querySelectorAll(`[data-page="${page}"]`).forEach(el => el.classList.add("active"));

            window.scrollTo({ top: 0, behavior: "smooth" });
        }

        function openRegistrationPage() {
            if (sonaraCurrentUser) {
                navigate("subscription");
                showToast("Sua conta já está criada. Confira os planos SONARA.");
                return;
            }
            closeAuthModal();
            navigate("register");
            document.getElementById("sonaraRegistrationForm")?.reset();
            document.getElementById("registerMessage").textContent = "";
            lucide.createIcons();
        }


        document.querySelectorAll("[data-page]").forEach(button => {
            button.addEventListener("click", () => navigate(button.dataset.page));
        });

        let stemLoading = false;
        let activeStemIndex = null;
        let stemSyncTimer = null;
        let masterStemVolume = 0.7;
        let stemVolumeLevels = [];
        let soloStemIndices = new Set();

        function stopStemPlayers(reset = true) {
            audioPlayer.pause();
            if (reset) { try { audioPlayer.currentTime = 0; } catch {} }
            if (stemSyncTimer) {
                clearInterval(stemSyncTimer);
                stemSyncTimer = null;
            }
            stemPlayers.forEach(player => {
                player.pause();
                if (reset) {
                    try { player.currentTime = 0; } catch {}
                }
            });
            activeStemIndex = null;
            updateAllStemsButton(false);
            stemPlayers.forEach((_, index) => updateStemButton(index, false));
        }

        function updateAllStemsButton(isPlaying, loading = false) {
            const button = document.getElementById("playAllStems");
            if (!button) return;
            button.disabled = loading;
            button.innerHTML = loading
                ? '<i data-lucide="loader-circle"></i> Carregando tracks...'
                : isPlaying
                    ? '<i data-lucide="pause"></i> Pausar seleção'
                    : '<i data-lucide="play"></i> Tocar seleção';
            const footerPlay = document.getElementById("playButton");
            if (footerPlay) {
                const hasActiveAudio = isPlaying || !audioPlayer.paused || stemPlayers.some(player => !player.paused);
                footerPlay.innerHTML = hasActiveAudio
                    ? '<i data-lucide="pause" size="17"></i>'
                    : '<i data-lucide="play" size="17"></i>';
            }
            lucide.createIcons();
        }

        function createStemPlayers() {
            if (stemPlayers.length || !currentTrack) return;
            stemPlayers = (currentTrack.stems || []).map(stem => {
                const player = new Audio();
                player.preload = "none";
                player.src = stem.url;
                player.volume = masterStemVolume;
                player.addEventListener("ended", () => {
                    const index = stemPlayers.indexOf(player);
                    if (index >= 0) updateStemButton(index, false);
                    if (stemPlayers.every(item => item.paused || item.ended)) {
                        updateAllStemsButton(false);
                        stopProgressSync();
                    }
                });
                player.addEventListener("error", () => {
                    const index = stemPlayers.indexOf(player);
                    if (index >= 0) {
                        updateStemButton(index, false);
                        showToast("Falha ao carregar: " + (currentTrack?.stems?.[index]?.name || "track"));
                    }
                });
                return player;
            });
        }

        function startProgressSync() {
            stopProgressSync();
            stemSyncTimer = setInterval(() => {
                const player = !audioPlayer.paused ? audioPlayer : (activeStemIndex === null ? stemPlayers.find(item => !item.paused) : stemPlayers[activeStemIndex]);
                if (!player || !Number.isFinite(player.duration)) return;
                document.getElementById("currentTime").textContent = formatAudioTime(player.currentTime);
                document.getElementById("durationTime").textContent = formatAudioTime(player.duration);
                document.getElementById("progressFill").style.width =
                    player.duration ? (player.currentTime / player.duration * 100) + "%" : "0%";
            }, 200);
        }

        function stopProgressSync() {
            if (stemSyncTimer) clearInterval(stemSyncTimer);
            stemSyncTimer = null;
        }

        function selectTrack(id) {
            const selected = tracks.find(t => t.id === Number(id));
            if (!selected) return;
            stopStemPlayers();
            audioPlayer.pause();
            currentTrack = selected;
            audioPlayer.pause(); audioPlayer.removeAttribute('src'); audioPlayer.load();
            stemPlayers = [];
            soloStemIndices = new Set();
            document.getElementById("playerTitle").textContent = currentTrack.title;
            document.getElementById("playerArtist").textContent = currentTrack.artist || "SONARA";
            document.getElementById("progressFill").style.width = "0%";
            document.getElementById("currentTime").textContent = "0:00";
            document.getElementById("durationTime").textContent = "0:00";

            const overlay = document.getElementById("multitrackOverlay");
            const cover = document.getElementById("multitrackCover");
            document.getElementById("multitrackTitle").textContent = currentTrack.title;
            document.getElementById("multitrackMeta").textContent =
                [currentTrack.artist, currentTrack.key, currentTrack.bpm !== "—" ? currentTrack.bpm + " BPM" : "", currentTrack.timeSignature]
                    .filter(Boolean).join(" · ");
            if (currentTrack.coverUrl) {
                cover.src = currentTrack.coverUrl;
                cover.hidden = false;
            } else {
                cover.removeAttribute("src");
                cover.hidden = true;
            }

            const download = document.getElementById("downloadMultitrack");
            updateDownloadAccessButton();
            download.onclick = handleDownloadAccess;

            const stems = currentTrack.stems || [];
            stemVolumeLevels = stems.map(() => 1);
            soloStemIndices = new Set();
            document.getElementById("stemCount").textContent = stems.length + (stems.length === 1 ? " track" : " tracks");
            const list = document.getElementById("stemList");
            list.innerHTML = stems.length ? stems.map((stem, index) => {
                const label = stem.name.replace(/^\d+_/, "").replace(/\\.[^.]+$/, "").replace(/[_-]+/g, " ");
                return `<div class="stem-row">
                    <div class="stem-index">${String(index + 1).padStart(2, "0")}</div>
                    <div class="stem-details"><strong>${escapeHTML(label)}</strong><span>${escapeHTML(stem.name)}</span></div>
                    <button class="stem-play stem-solo" id="stemPlay-${index}" type="button" aria-pressed="false" onclick="toggleSolo(${index})"><i data-lucide="headphones"></i> SOLO</button>
                    <label class="stem-volume"><i data-lucide="volume-2"></i><input type="range" min="0" max="100" value="100" aria-label="Volume de ${escapeHTML(label)}" oninput="setStemVolume(${index}, this.value)"></label>
                </div>`;
            }).join("") : '<p class="stem-empty">Nenhuma track de áudio foi encontrada nesta música.</p>';

            overlay.classList.add("active");
            overlay.setAttribute("aria-hidden", "false");
            updateAllStemsButton(false);
            lucide.createIcons();
        }

        function closeMultitrack() {
            stopStemPlayers();
            const overlay = document.getElementById("multitrackOverlay");
            overlay.classList.remove("active");
            overlay.setAttribute("aria-hidden", "true");
        }

        function updateStemButton(index, isPlaying, loading = false) {
            const button = document.getElementById("stemPlay-" + index);
            if (!button) return;
            const solo = soloStemIndices.has(index);
            button.disabled = loading;
            button.classList.toggle("solo-active", solo);
            button.setAttribute("aria-pressed", String(solo));
            button.innerHTML = loading
                ? '<i data-lucide="loader-circle"></i>'
                : solo
                    ? '<i data-lucide="headphones"></i> SOLO ATIVO'
                    : '<i data-lucide="headphones"></i> SOLO';
            lucide.createIcons();
        }


        function toggleSolo(index) {
            if (!audioPlayer.paused) { audioPlayer.pause(); updateAllStemsButton(false); }
            if (soloStemIndices.has(index)) soloStemIndices.delete(index);
            else soloStemIndices.add(index);
            document.querySelectorAll(".stem-solo").forEach((button, buttonIndex) => {
                const active = soloStemIndices.has(buttonIndex);
                button.classList.toggle("solo-active", active);
                button.setAttribute("aria-pressed", String(active));
                button.innerHTML = active
                    ? '<i data-lucide="headphones"></i> SOLO ATIVO'
                    : '<i data-lucide="headphones"></i> SOLO';
            });
            stemPlayers.forEach((player, playerIndex) => {
                const audible = !soloStemIndices.size || soloStemIndices.has(playerIndex);
                player.volume = (stemVolumeLevels[playerIndex] ?? 1) * masterStemVolume * (audible ? 1 : 0);
                if (!audible) player.pause();
            });
            updateAllStemsButton(stemPlayers.some(player => !player.paused));
            lucide.createIcons();
        }

        async function toggleStem(index) {
            if (stemLoading) return;
            createStemPlayers();
            const selected = stemPlayers[index];
            if (!selected) {
                showToast("Esta track não possui um arquivo de áudio disponível.");
                return;
            }
            if (!selected.paused) {
                selected.pause();
                updateStemButton(index, false);
                updateAllStemsButton(false);
                return;
            }

            stopStemPlayers();
            stemLoading = true;
            updateStemButton(index, false, true);
            try {
                selected.preload = "auto";
                selected.load();
                selected.currentTime = 0;
                // play() é chamado diretamente no clique para respeitar a política de áudio do Safari.
                await selected.play();
                activeStemIndex = index;
                updateStemButton(index, true);
                updateAllStemsButton(false);
                startProgressSync();
            } catch (error) {
                updateStemButton(index, false);
                showToast(error.message || "Não foi possível reproduzir esta track.");
            } finally {
                stemLoading = false;
            }
        }

        function setStemVolume(index, value) {
            if (stemPlayers[index]) {
                stemVolumeLevels[index] = Number(value) / 100;
                stemPlayers[index].volume = stemVolumeLevels[index] * masterStemVolume * (soloStemIndices.size && !soloStemIndices.has(index) ? 0 : 1);
            }
        }

        async function toggleAllStems() {
            if (stemLoading) return;
            createStemPlayers();
            if (!stemPlayers.length) {
                showToast("Esta música não possui tracks de áudio disponíveis.");
                return;
            }
            if (!soloStemIndices.size) {
                if (!currentTrack.mixUrl) { showToast('Mixagem desta música indisponível.'); return; }
                if (!audioPlayer.paused) { audioPlayer.pause(); updateAllStemsButton(false); stopProgressSync(); return; }
                stemLoading = true; updateAllStemsButton(false, true);
                try {
                    if (audioPlayer.src !== currentTrack.mixUrl) { audioPlayer.src = currentTrack.mixUrl; audioPlayer.preload = 'auto'; audioPlayer.load(); }
                    audioPlayer.volume = masterStemVolume;
                    await audioPlayer.play();
                    activeStemIndex = null; updateAllStemsButton(true); startProgressSync();
                } catch (error) { audioPlayer.pause(); updateAllStemsButton(false); showToast(error.message || 'Não foi possível reproduzir a mixagem.'); }
                finally { stemLoading = false; }
                return;
            }
            const selectedIndices = [...soloStemIndices];
            const selectedPlayers = selectedIndices.map(index => stemPlayers[index]).filter(Boolean);
            const allPlaying = selectedPlayers.length > 0 && selectedPlayers.every(player => !player.paused);
            if (allPlaying) {
                selectedPlayers.forEach(player => player.pause());
                stemPlayers.forEach((player, index) => updateStemButton(index, !player.paused));
                updateAllStemsButton(false);
                stopProgressSync();
                return;
            }

            stemLoading = true;
            updateAllStemsButton(false, true);
            try {
                stemPlayers.forEach(player => player.pause());
                selectedPlayers.forEach(player => {
                    player.preload = "auto";
                    player.load();
                    player.currentTime = 0;
                    const index = stemPlayers.indexOf(player);
                    player.volume = (stemVolumeLevels[index] ?? 1) * masterStemVolume * (soloStemIndices.size && !soloStemIndices.has(index) ? 0 : 1);
                });
                const results = await Promise.allSettled(selectedPlayers.map(player => player.play()));
                const failed = results.findIndex(result => result.status === "rejected");
                if (failed !== -1) {
                    selectedPlayers.forEach(player => player.pause());
                    throw new Error("Não foi possível iniciar a prévia de " + (currentTrack.stems[selectedIndices[failed]]?.name || "um instrumento") + ".");
                }
                stemPlayers.forEach((player, index) => updateStemButton(index, !player.paused));
                activeStemIndex = selectedIndices[0] ?? null;
                updateAllStemsButton(true);
                startProgressSync();
            } catch (error) {
                stemPlayers.forEach((player, index) => {
                    player.pause();
                    updateStemButton(index, false);
                });
                updateAllStemsButton(false);
                showToast(error.message || "Falha ao iniciar a prévia.");
            } finally {
                stemLoading = false;
            }
        }

        function togglePlay() {
            if (!currentTrack) {
                showToast("Selecione uma música primeiro.");
                return;
            }
            const overlay = document.getElementById("multitrackOverlay");
            if (!overlay.classList.contains("active")) selectTrack(currentTrack.id);
            toggleAllStems();
        }

        function formatAudioTime(seconds) {
            if (!Number.isFinite(seconds)) return "0:00";
            const minutes = Math.floor(seconds / 60);
            const remainder = Math.floor(seconds % 60).toString().padStart(2, "0");
            return minutes + ":" + remainder;
        }

        audioPlayer.addEventListener("timeupdate", () => {
            document.getElementById("currentTime").textContent = formatAudioTime(audioPlayer.currentTime);
            document.getElementById("progressFill").style.width = audioPlayer.duration
                ? (audioPlayer.currentTime / audioPlayer.duration * 100) + "%" : "0%";
        });
        audioPlayer.addEventListener("loadedmetadata", () => {
            document.getElementById("durationTime").textContent = formatAudioTime(audioPlayer.duration);
        });
        audioPlayer.addEventListener("play", () => {
            playing = true;
            document.getElementById("playButton").innerHTML = '<i data-lucide="pause" size="17"></i>';
            lucide.createIcons();
        });
        audioPlayer.addEventListener("pause", () => {
            playing = false;
            document.getElementById("playButton").innerHTML = '<i data-lucide="play" size="17"></i>';
            lucide.createIcons();
        });
        audioPlayer.addEventListener("ended", () => {
            document.getElementById("progressFill").style.width = "0%";
        });
        document.getElementById("progressBar").addEventListener("click", event => {
            const active = activeStemIndex === null ? stemPlayers.filter(player => !player.paused) : [stemPlayers[activeStemIndex]].filter(Boolean);
            const reference = active[0];
            if (!reference || !Number.isFinite(reference.duration) || !reference.duration) return;
            const bounds = event.currentTarget.getBoundingClientRect();
            const nextTime = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width)) * reference.duration;
            active.forEach(player => { if (Number.isFinite(player.duration)) player.currentTime = Math.min(nextTime, player.duration); });
        });
        document.querySelector('.player-volume input[type="range"]').addEventListener("input", event => {
            masterStemVolume = Number(event.target.value) / 100;
            stemPlayers.forEach((player, index) => {
                player.volume = (stemVolumeLevels[index] ?? 1) * masterStemVolume;
            });
            audioPlayer.volume = masterStemVolume;
        });
        audioPlayer.volume = 0.7;

        
        function renderHeroSlideshow() {
            const trackElement = document.getElementById("heroBannerTrack");
            if (!trackElement) return;

            const bannerTracks = tracks.filter(track => track.coverUrl);
            if (!bannerTracks.length) {
                trackElement.innerHTML = '<div class="hero-banner-empty">Novos banners em breve</div>';
                trackElement.style.animation = "none";
                return;
            }

            const createCards = (items, copy) => items.map((track, index) =>
                '<div class="hero-banner-card">' +
                    '<img src="' + escapeHTML(track.coverUrl) + '" alt="' + escapeHTML(track.title || "Banner SONARA") + '"' +
                    (copy ? ' aria-hidden="true"' : ' loading="lazy"') + '>' +
                '</div>'
            ).join("");

            // Duas cópias idênticas permitem o movimento contínuo sem um salto no reinício.
            trackElement.innerHTML = createCards(bannerTracks, false) + createCards(bannerTracks, true);
            trackElement.style.animation = bannerTracks.length > 1 ? "" : "none";
        }

        async function loadPublicCatalog() {
            const badge = document.getElementById("catalogBadge");
            try {
                const [response, featureResponse] = await Promise.all([
                    fetch(SONARA_CATALOG_API + "/catalog/tracks"),
                    fetch(SONARA_CATALOG_API + "/catalog/homepage-features")
                ]);
                if (!response.ok) throw new Error("Catálogo indisponível");
                const data = await response.json();
                if (featureResponse.ok) homepageFeatureSelection = await featureResponse.json();
                const covers = ["cover-one", "cover-two", "cover-three", "cover-four"];
                tracks = (data.items || []).map((track, index) => ({
                    id: Number(track.id),
                    title: track.title,
                    artist: track.artist || "SONARA",
                    key: track.musical_key || "—",
                    bpm: track.bpm || "—",
                    genre: (track.categories || [track.category || "Multitrack"]).join(", "),
                    cover: covers[index % covers.length],
                    coverUrl: track.cover_url ? SONARA_CATALOG_API.replace(/\/api\/v1$/, "") + track.cover_url : "",
                    audioUrl: SONARA_CATALOG_API.replace(/\/api\/v1$/, "") + (track.audio_url || ("/api/v1/tracks/" + track.id + "/audio")),
                    mixUrl: SONARA_CATALOG_API.replace(/\/api\/v1$/, "") + (track.mix_url || ("/api/v1/tracks/" + track.id + "/mix")),
                    timeSignature: track.time_signature || "4/4",
                    zipDownloadUrl: track.zip_download_url ? SONARA_CATALOG_API.replace(/\/api\/v1$/, "") + track.zip_download_url : "",
                    stems: (track.stems || []).map(stem => ({ ...stem, url: SONARA_CATALOG_API.replace(/\/api\/v1$/, "") + stem.url }))
                }));
                if (badge) badge.textContent = "CATÁLOGO OFICIAL";
                searchTerm = document.getElementById("searchInput").value;
                renderAll();
                renderFeaturedRails();
            } catch {
                tracks = [];
                if (badge) badge.textContent = "CATÁLOGO INDISPONÍVEL";
                renderAll();
                document.querySelector("#emptyState p").textContent = "Não foi possível carregar o catálogo. Verifique se a API SONARA está ativa.";
            }
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

        // O heroWave antigo foi removido em favor do slideshow.
        // Mantemos a inicialização protegida para não interromper o restante do app.
        const wave = document.getElementById("heroWave");
        if (wave) {
            const heights = [25, 42, 65, 95, 70, 115, 85, 55, 100, 125, 75, 45, 95, 115, 70, 38, 85, 105, 55, 35, 75, 95, 50, 25];
            wave.innerHTML = heights.map((h, i) =>
                `<span style="height:${h}px;animation-delay:${i * .07}s"></span>`
            ).join("");
        }

        renderAll();
        loadPublicCatalog();
        lucide.createIcons();

/* SONARA user authentication */
const SONARA_API_BASE = "http://127.0.0.1:8000/api/v1";
const SONARA_USER_TOKEN = "sonaraUserAccessToken";
let sonaraCurrentUser = null;
let authMode = "login";
let passwordResetToken = new URLSearchParams(window.location.search).get("reset_token") || "";

function updateDownloadAccessButton() {
    const button = document.getElementById("downloadMultitrack");
    if (!button) return;
    const isLoggedIn = Boolean(sonaraCurrentUser);
    button.innerHTML = isLoggedIn
        ? '<i data-lucide="lock-keyhole"></i> Assine para baixar'
        : '<i data-lucide="user-plus"></i> Cadastre-se para baixar';
    button.setAttribute("aria-label", isLoggedIn ? "Assine para baixar" : "Cadastre-se para baixar");
    lucide.createIcons();
}

function handleDownloadAccess() {
    if (!sonaraCurrentUser) {
        openAuthModal();
        setAuthMode("register");
        return;
    }
    navigate("subscription");
    showToast("O download será liberado após a ativação de um plano compatível.");
}

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
        ? 'Criar conta e continuar <i data-lucide="arrow-right"></i>'
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
    document.getElementById("forgotPasswordForm").hidden = true;
    document.getElementById("resetPasswordForm").hidden = true;
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
        document.getElementById("authTabs").hidden = true;
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
        avatar.hidden = false;
        avatar.setAttribute("aria-label", "Conta de " + sonaraCurrentUser.full_name);
        updateDownloadAccessButton();
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
document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeAuthModal();
});

function showForgotPassword() {
    document.getElementById("userAuthForm").hidden = true;
    document.getElementById("forgotPasswordForm").hidden = false;
    document.getElementById("resetPasswordForm").hidden = true;
    document.getElementById("authAccount").hidden = true;
    document.getElementById("authTitle").textContent = "Recuperar senha";
    document.getElementById("authDescription").textContent = "Informe o e-mail da sua conta. Enviaremos um link seguro para criar uma nova senha.";
    document.getElementById("forgotEmail").value = document.getElementById("authEmail").value.trim();
    document.getElementById("forgotMessage").textContent = "";
    document.getElementById("forgotEmail").focus();
}

function showResetPassword() {
    document.getElementById("userAuthForm").hidden = true;
    document.getElementById("forgotPasswordForm").hidden = true;
    document.getElementById("resetPasswordForm").hidden = false;
    document.getElementById("authAccount").hidden = true;
    document.getElementById("authTitle").textContent = "Criar nova senha";
    document.getElementById("authDescription").textContent = "Escolha uma nova senha para acessar sua conta SONARA.";
    document.getElementById("resetMessage").textContent = "";
}

document.getElementById("forgotPasswordLink").addEventListener("click", showForgotPassword);
document.getElementById("backToLoginFromReset").addEventListener("click", () => {
    passwordResetToken = "";
    window.history.replaceState({}, document.title, window.location.pathname);
    document.getElementById("resetPasswordForm").hidden = true;
    document.getElementById("userAuthForm").hidden = false;
    setAuthMode("login");
});
document.getElementById("backToLoginFromForgot").addEventListener("click", () => {
    document.getElementById("forgotPasswordForm").hidden = true;
    document.getElementById("userAuthForm").hidden = false;
    setAuthMode("login");
});

document.getElementById("forgotPasswordForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = document.getElementById("forgotSubmit");
    const message = document.getElementById("forgotMessage");
    button.disabled = true;
    message.textContent = "";
    try {
        const result = await sonaraApi("/auth/forgot-password", {
            method: "POST",
            body: JSON.stringify({ email: document.getElementById("forgotEmail").value.trim() })
        });
        message.style.color = "#36C98F";
        message.textContent = result.message || "Se o e-mail estiver cadastrado, você receberá um link para redefinir sua senha.";
    } catch (error) {
        message.style.color = "";
        message.textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

document.getElementById("resetPasswordForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = document.getElementById("resetSubmit");
    const message = document.getElementById("resetMessage");
    const password = document.getElementById("resetNewPassword").value;
    const confirmation = document.getElementById("resetConfirmPassword").value;
    if (password !== confirmation) {
        message.textContent = "As senhas não coincidem.";
        return;
    }
    button.disabled = true;
    message.textContent = "";
    try {
        const result = await sonaraApi("/auth/reset-password", {
            method: "POST",
            body: JSON.stringify({ token: passwordResetToken, new_password: password })
        });
        passwordResetToken = "";
        window.history.replaceState({}, document.title, window.location.pathname);
        document.getElementById("resetPasswordForm").reset();
        document.getElementById("resetPasswordForm").hidden = true;
        document.getElementById("userAuthForm").hidden = false;
        setAuthMode("login");
        document.getElementById("authMessage").style.color = "#36C98F";
        document.getElementById("authMessage").textContent = result.message || "Senha redefinida. Faça login com sua nova senha.";
    } catch (error) {
        message.style.color = "";
        message.textContent = error.message;
    } finally {
        button.disabled = false;
    }
});

document.getElementById("userAuthForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = document.getElementById("authSubmit");
    const message = document.getElementById("authMessage");
    const email = document.getElementById("authEmail").value.trim();
    const password = document.getElementById("authPassword").value;
    button.disabled = true;
    message.textContent = "";
    try {
        const tokenResult = await sonaraApi("/auth/login", {
            method: "POST",
            body: JSON.stringify({ email, password })
        });
        sessionStorage.setItem(SONARA_USER_TOKEN, tokenResult.access_token);
        sonaraCurrentUser = await sonaraApi("/auth/me", { method: "GET" }, tokenResult.access_token);
        document.getElementById("userAccountButton").textContent =
            sonaraCurrentUser.full_name.trim().charAt(0).toUpperCase();
        document.getElementById("userAccountButton").hidden = false;
        updateDownloadAccessButton();
        document.getElementById("userAuthForm").reset();
        closeAuthModal();
        showToast("Login realizado com sucesso!");
    } catch (error) {
        if (error instanceof TypeError) {
            message.textContent = "Não foi possível conectar à SONARA. Verifique se o backend está iniciado.";
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
    updateDownloadAccessButton();
    document.getElementById("userAccountButton").textContent = "S";
    document.getElementById("userAccountButton").hidden = true;
    document.getElementById("userAccountButton").setAttribute("aria-label", "Entrar ou acessar minha conta");
    closeAuthModal();
    showToast("Você saiu da sua conta.");
});


document.getElementById("sonaraRegistrationForm").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const button = document.getElementById("registerSubmit");
    const message = document.getElementById("registerMessage");
    const values = Object.fromEntries(new FormData(form).entries());
    message.textContent = "";
    if (values.password !== values.password_confirm) {
        message.textContent = "As senhas não coincidem.";
        document.getElementById("registerPasswordConfirm").focus();
        return;
    }
    if (!values.full_name.trim().includes(" ")) {
        message.textContent = "Informe seu nome e sobrenome.";
        document.getElementById("registerFullName").focus();
        return;
    }
    button.disabled = true;
    button.innerHTML = '<i data-lucide="loader-circle"></i> Criando conta...';
    lucide.createIcons();
    try {
        await sonaraApi("/auth/register", {
            method: "POST",
            body: JSON.stringify({
                full_name: values.full_name.trim(),
                email: values.email.trim(),
                password: values.password,
            })
        });
        const tokenResult = await sonaraApi("/auth/login", {
            method: "POST",
            body: JSON.stringify({ email: values.email.trim(), password: values.password })
        });
        sessionStorage.setItem(SONARA_USER_TOKEN, tokenResult.access_token);
        sonaraCurrentUser = await sonaraApi("/auth/me", { method: "GET" }, tokenResult.access_token);
        document.getElementById("userAccountButton").textContent =
            sonaraCurrentUser.full_name.trim().charAt(0).toUpperCase();
        document.getElementById("userAccountButton").hidden = false;
        updateDownloadAccessButton();
        form.reset();
        navigate("subscription");
        showToast("Conta criada! Continue para o acesso vitalício SONARA.");
    } catch (error) {
        if (error instanceof TypeError) {
            message.textContent = "Não foi possível conectar à SONARA. Verifique se o backend está iniciado.";
        } else if (error.status === 409) {
            message.textContent = "Este e-mail já possui uma conta.";
        } else {
            message.textContent = error.message;
        }
    } finally {
        button.disabled = false;
        button.innerHTML = 'Criar minha conta <i data-lucide="arrow-right"></i>';
        lucide.createIcons();
    }
});

if (passwordResetToken) {
    openAuthModal();
    showResetPassword();
}
restoreSonaraUserSession();
