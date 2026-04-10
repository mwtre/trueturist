(function () {
  const form = document.getElementById("video-form");
  const promptEl = document.getElementById("video-prompt");
  const modelEl = document.getElementById("video-model");
  const providerEl = document.getElementById("video-provider");
  const runBtn = document.getElementById("video-run");
  const statusEl = document.getElementById("video-status");
  const outputPre = document.getElementById("video-output");
  const outputCode = outputPre ? outputPre.querySelector("code") : null;

  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    const prompt = String(promptEl?.value || "").trim();
    const model = String(modelEl?.value || "").trim() || "tencent/HunyuanVideo";
    const provider = String(providerEl?.value || "").trim() || "fal-ai";

    outputPre.style.display = "none";
    if (outputCode) outputCode.textContent = "";

    if (!prompt) {
      statusEl.textContent = "Enter a prompt.";
      statusEl.classList.remove("muted");
      return;
    }

    runBtn.disabled = true;
    statusEl.classList.remove("muted");
    statusEl.textContent = "Generating…";

    try {
      const res = await fetch("/api/video/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, model, provider }),
      });

      const data = await res.json().catch(() => null);
      if (!res.ok) {
        const detail = data && (data.detail || data.error) ? String(data.detail || data.error) : `HTTP ${res.status}`;
        statusEl.textContent = `Error: ${detail}`;
        return;
      }

      statusEl.textContent = "OK";
      if (outputCode) {
        outputCode.textContent = JSON.stringify(data, null, 2);
        outputPre.style.display = "block";
      }
    } catch (err) {
      statusEl.textContent = `Error: ${String(err)}`;
    } finally {
      runBtn.disabled = false;
    }
  });
})();

