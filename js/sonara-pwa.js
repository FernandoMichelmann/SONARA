(() => {
  if (!("serviceWorker" in navigator) || !/^https?:$/.test(window.location.protocol)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./service-worker.js", { scope: "./" })
      .then(registration => registration.update())
      .catch(error => console.warn("SONARA: não foi possível ativar o modo aplicativo.", error));
  });
})();