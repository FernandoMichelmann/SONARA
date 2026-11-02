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
