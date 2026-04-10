(function () {
  /** Match app.default_dest_codes.DEFAULT_DEST_CODES length (progress bar hint). */
  const TOTAL_DESTINATIONS = 181;
  const MAX_RANGE_DAYS = 14;

  const QUICK_MONTHS = 6;
  const QUICK_TRIP_DAYS = 7;

  const quickForm = document.getElementById("quick-form");
  const quickOriginEl = document.getElementById("quick-origin");
  const quickRegionEl = document.getElementById("quick-region");
  const quickExcludeUkEl = document.getElementById("quick-exclude-uk");
  const quickRunBtn = document.getElementById("quick-run");
  const quickStatusEl = document.getElementById("quick-status");
  const quickProgressWrap = document.querySelector(".quick-progress");
  const quickProgressBar = document.getElementById("quick-progress-bar");
  const withHotelsEl = document.getElementById("with-hotels");
  const hotelTopNEl = document.getElementById("hotel-top-n");
  const hotelFiveStarEl = document.getElementById("hotel-five-star");
  const hotelWorkersEl = document.getElementById("hotel-workers");

  const form = document.getElementById("scan-form");
  const calendarForm = document.getElementById("calendar-form");
  const originEl = document.getElementById("origin");
  const dateFromEl = document.getElementById("date-from");
  const dateToEl = document.getElementById("date-to");
  const roundTripEl = document.getElementById("round-trip");
  const tripDaysWrap = document.getElementById("trip-days-wrap");
  const tripDaysEl = document.getElementById("trip-days");
  const nonStopEl = document.getElementById("non-stop");
  const nonEuOnlyEl = document.getElementById("non-eu-only");
  const excludeDomesticEl = document.getElementById("exclude-domestic");
  const excludeUkEl = document.getElementById("exclude-uk");
  const runBtn = document.getElementById("run");
  const statusEl = document.getElementById("status");
  const tbody = document.getElementById("tbody");
  const countBadge = document.getElementById("count-badge");
  const chartNote = document.getElementById("chart-note");
  const progressWrap = document.querySelector("#scan-form").closest(".panel").querySelector(".progress-wrap");
  const progressBar = document.getElementById("progress-bar");
  const calOriginEl = document.getElementById("cal-origin");
  const calFromEl = document.getElementById("cal-from");
  const calMonthsEl = document.getElementById("cal-months");
  const calTripDaysEl = document.getElementById("cal-trip-days");
  const calNonStopEl = document.getElementById("cal-non-stop");
  const calNonEuOnlyEl = document.getElementById("cal-non-eu-only");
  const calExcludeDomesticEl = document.getElementById("cal-exclude-domestic");
  const calExcludeUkEl = document.getElementById("cal-exclude-uk");
  const calRunBtn = document.getElementById("cal-run");
  const calStatusEl = document.getElementById("cal-status");
  const calProgressWrap = document.querySelector(".cal-progress");
  const calProgressBar = document.getElementById("cal-progress-bar");

  const videoForm = document.getElementById("video-form");
  const videoPromptEl = document.getElementById("video-prompt");
  const videoModelEl = document.getElementById("video-model");
  const videoProviderEl = document.getElementById("video-provider");
  const videoRunBtn = document.getElementById("video-run");
  const videoStatusEl = document.getElementById("video-status");

  let chart = null;
  let activeAbortController = null;

  const today = new Date();
  const defFrom = new Date(today.getTime() + 60 * 86400000);
  const defTo = new Date(today.getTime() + 66 * 86400000);
  dateFromEl.valueAsDate = defFrom;
  dateToEl.valueAsDate = defTo;
  calFromEl.valueAsDate = new Date(today.getTime() + 86400000);

  function daySpanInclusive(fromStr, toStr) {
    const a = new Date(`${fromStr}T12:00:00`);
    const b = new Date(`${toStr}T12:00:00`);
    return Math.floor((b - a) / 86400000) + 1;
  }

  /** Local calendar date YYYY-MM-DD, offset days from base (default: today). */
  function localYmdPlusDays(base, addDays) {
    const d = new Date(base.getTime());
    d.setDate(d.getDate() + addDays);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function syncTripDaysUi() {
    const rt = roundTripEl.checked;
    tripDaysWrap.classList.toggle("field-disabled", !rt);
    tripDaysEl.disabled = !rt;
  }

  roundTripEl.addEventListener("change", syncTripDaysUi);
  syncTripDaysUi();

  function syncQuickRegionUi() {
    const eu = quickRegionEl.value === "eu";
    quickExcludeUkEl.disabled = eu;
    if (eu) {
      quickExcludeUkEl.checked = false;
    }
  }
  quickRegionEl.addEventListener("change", syncQuickRegionUi);
  syncQuickRegionUi();

  quickForm.addEventListener("submit", (e) => {
    e.preventDefault();
    if (activeAbortController) {
      activeAbortController.abort();
      activeAbortController = null;
    }

    bestByDest.clear();
    completed = 0;
    tbody.innerHTML = "";
    countBadge.textContent = "";
    chartNote.textContent = "";
    if (chart) {
      chart.destroy();
      chart = null;
    }

    const origin = quickOriginEl.value.trim().toUpperCase();
    if (origin.length !== 3) {
      quickStatusEl.textContent = "Origin must be a 3-letter IATA code.";
      return;
    }

    const fromDate = localYmdPlusDays(new Date(), 1);
    totalSteps = TOTAL_DESTINATIONS;
    setBusy(true);
    quickProgressWrap.hidden = false;
    quickProgressBar.style.width = "0%";
    progressWrap.hidden = true;
    calProgressWrap.hidden = true;
    quickStatusEl.textContent = "Connecting (quick calendar A/R)…";
    quickStatusEl.classList.remove("muted");
    statusEl.textContent = "";
    calStatusEl.textContent = "";

    const region = quickRegionEl.value;
    let nonEuOnly = "false";
    let euOnly = "false";
    if (region === "eu") {
      euOnly = "true";
    } else if (region === "international") {
      nonEuOnly = "true";
    }
    const excludeUk = quickExcludeUkEl.checked ? "true" : "false";

    const qs = new URLSearchParams({
      origin,
      from_date: fromDate,
      months: String(QUICK_MONTHS),
      trip_days: String(QUICK_TRIP_DAYS),
      non_stop: "false",
      non_eu_only: nonEuOnly,
      eu_only: euOnly,
      exclude_domestic: "false",
      exclude_uk: excludeUk,
    });
    applyHotelParams(qs);
    const regLabel = region === "all" ? "all regions" : region === "eu" ? "EU only" : "international";
    const label = `Quick A/R (${regLabel}) · ${fromDate} +${QUICK_MONTHS} mo · ${QUICK_TRIP_DAYS}d trip`;
    runSseScan(apiUrl("/api/calendar/stream", qs), label, quickStatusEl, quickProgressBar, quickProgressWrap);
  });

  if (videoForm) {
    videoForm.addEventListener("submit", async (e) => {
      e.preventDefault();

      const prompt = (videoPromptEl?.value || "").trim();
      const model = (videoModelEl?.value || "").trim() || "tencent/HunyuanVideo";
      const provider = (videoProviderEl?.value || "").trim() || "fal-ai";

      if (!prompt) {
        videoStatusEl.textContent = "Enter a prompt.";
        videoStatusEl.classList.remove("muted");
        return;
      }

      videoRunBtn.disabled = true;
      videoStatusEl.classList.remove("muted");
      videoStatusEl.textContent = "Generating…";
      try {
        const res = await fetch("/api/video/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt, model, provider }),
        });
        const data = await res.json().catch(() => null);
        if (!res.ok) {
          const detail = data && (data.detail || data.error) ? String(data.detail || data.error) : `HTTP ${res.status}`;
          videoStatusEl.textContent = `Error: ${detail}`;
          return;
        }

        const resultStr = data?.result ? JSON.stringify(data.result, null, 2) : JSON.stringify(data, null, 2);
        videoStatusEl.textContent = "OK";
        const pre = document.createElement("pre");
        pre.style.marginTop = ".5rem";
        const code = document.createElement("code");
        code.textContent = resultStr;
        pre.appendChild(code);
        videoStatusEl.appendChild(pre);
      } catch (err) {
        videoStatusEl.textContent = `Error: ${String(err)}`;
      } finally {
        videoRunBtn.disabled = false;
      }
    });
  }

  function formatDuration(min) {
    if (min == null || min < 0 || !Number.isFinite(min)) return "—";
    const h = Math.floor(min / 60);
    const m = min % 60;
    return `${h}h ${m.toString().padStart(2, "0")}m`;
  }

  function formatSchedule(r) {
    if (r.error) return "—";
    const o = r.outbound_times_local || "";
    const i = r.inbound_times_local || "";
    if (!o && !i) {
      if (r.departure_date || r.return_date) return "Calendar (no leg times)";
      return "—";
    }
    const lines = [];
    if (o) lines.push(`Out: ${o}`);
    if (i) lines.push(`Ret: ${i}`);
    return lines.join("\n");
  }

  function formatHotelNightlyCell(r) {
    if (r.error) return "—";
    if (r.hotel_error) {
      const e = r.hotel_error;
      return e.length > 36 ? `${e.slice(0, 36)}…` : e;
    }
    if (r.hotel_nightly_usd != null && r.hotel_nightly_usd !== undefined) {
      return `${Number(r.hotel_nightly_usd).toFixed(0)}`;
    }
    return "—";
  }

  function formatHotelStayCell(r) {
    if (r.error || r.hotel_error) return "—";
    if (r.hotel_stay_usd != null && r.hotel_stay_usd !== undefined) {
      return `${Number(r.hotel_stay_usd).toFixed(0)}`;
    }
    return "—";
  }

  function formatHotelOtaCell(r) {
    if (r.hotel_ota) return r.hotel_ota;
    if (r.hotel_sample_name && (r.hotel_nightly_usd != null || r.hotel_stay_usd != null)) {
      const s = r.hotel_sample_name;
      return s.length > 28 ? `${s.slice(0, 28)}…` : s;
    }
    return "—";
  }

  /** @param {URLSearchParams} qs */
  function applyHotelParams(qs) {
    const on = withHotelsEl.checked;
    qs.set("with_hotels", on ? "true" : "false");
    const raw = Number.parseInt(hotelTopNEl.value, 10);
    const n = Number.isFinite(raw) ? Math.min(40, Math.max(1, raw)) : 24;
    qs.set("hotel_top_n", on ? String(n) : "0");
    qs.set("hotel_five_star", on && hotelFiveStarEl.checked ? "true" : "false");
    const hw = Number.parseInt(hotelWorkersEl.value, 10);
    const workers = Number.isFinite(hw) ? Math.min(12, Math.max(1, hw)) : 5;
    qs.set("hotel_workers", on ? String(workers) : "5");
  }

  function sortRows(rows) {
    return [...rows].sort((a, b) => {
      const errA = a.error != null;
      const errB = b.error != null;
      if (errA !== errB) return errA ? 1 : -1;
      if (a.price !== b.price) return a.price - b.price;
      return a.destination.localeCompare(b.destination);
    });
  }

  function renderTable(rows) {
    const sorted = sortRows(rows);
    tbody.innerHTML = "";
    sorted.forEach((r, i) => {
      const tr = document.createElement("tr");
      if (r.error) tr.classList.add("row-error");
      const priceStr =
        r.error != null ? r.error.slice(0, 80) : `${r.price.toFixed(0)} ${r.currency || "EUR"}`;
      const out = r.departure_date || "—";
      const ret = r.return_date || "—";
      const name = r.destination_name || "—";
      const sched = formatSchedule(r);
      const hN = formatHotelNightlyCell(r);
      const hS = formatHotelStayCell(r);
      const hO = formatHotelOtaCell(r);
      tr.innerHTML = `
        <td class="num">${i + 1}</td>
        <td class="mono"><strong>${r.destination}</strong></td>
        <td class="airport-name">${name}</td>
        <td class="num">${priceStr}</td>
        <td class="num mono">${out}</td>
        <td class="num mono">${ret}</td>
        <td class="schedule-cell mono">${sched.replace(/\n/g, "<br/>")}</td>
        <td class="num mono">${hN}</td>
        <td class="num mono">${hS}</td>
        <td class="airport-name">${hO}</td>
        <td class="num">${r.error != null || (r.stops ?? -1) < 0 ? "—" : r.stops}</td>
        <td class="num">${formatDuration(r.duration_minutes)}</td>`;
      tbody.appendChild(tr);
    });
    countBadge.textContent = sorted.length ? `(${sorted.length} destinations)` : "";
  }

  function updateChart(rows, labelHint) {
    const ok = rows.filter((r) => !r.error);
    const sorted = sortRows(ok).slice(0, 18);
    const labels = sorted.map((r) => r.destination);
    const prices = sorted.map((r) => r.price);

    const ctx = document.getElementById("price-chart").getContext("2d");
    if (chart) chart.destroy();
    chart = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Best fare",
            data: prices,
            backgroundColor: "rgba(61, 156, 245, 0.65)",
            borderColor: "rgba(61, 156, 245, 1)",
            borderWidth: 1,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: {
            grid: { color: "rgba(45, 58, 74, 0.8)" },
            ticks: { color: "#8b9bab" },
            title: { display: true, text: "Price", color: "#8b9bab" },
          },
          y: {
            grid: { display: false },
            ticks: { color: "#e8eef4", font: { size: 11 } },
          },
        },
      },
    });
    chartNote.textContent = labelHint || "";
  }

  const bestByDest = new Map();
  let completed = 0;
  let totalSteps = TOTAL_DESTINATIONS;

  function setBusy(busy) {
    runBtn.disabled = busy;
    calRunBtn.disabled = busy;
    quickRunBtn.disabled = busy;
  }

  function apiUrl(pathWithLeadingSlash, searchParams) {
    const u = new URL(pathWithLeadingSlash, window.location.origin);
    u.search = searchParams instanceof URLSearchParams ? searchParams.toString() : String(searchParams);
    return u.toString();
  }

  /**
   * @param {string} streamUrl
   * @param {string} chartLabelBase
   * @param {HTMLElement} stEl
   * @param {HTMLElement} pBar
   * @param {HTMLElement} pWrap
   */
  function runSseScan(streamUrl, chartLabelBase, stEl, pBar, pWrap) {
    function refreshFromMap() {
      const rows = Array.from(bestByDest.values());
      renderTable(rows);
      updateChart(rows, chartLabelBase);
    }

    let streamFinishedOk = false;
    let scanHadFatalError = false;
    let hotelPhaseActive = false;

    function handleEventPayload(text) {
      let msg;
      try {
        msg = JSON.parse(text);
      } catch {
        stEl.textContent = "Bad event from server (invalid JSON).";
        return;
      }
      if (msg.kind === "progress") {
        completed = Math.min(completed + 1, totalSteps);
        pBar.style.width = `${Math.round((completed / totalSteps) * 100)}%`;
        return;
      }
      if (msg.kind === "error" && msg.detail) {
        scanHadFatalError = true;
        stEl.textContent = `Scan failed: ${msg.detail}`;
        stEl.classList.remove("muted");
        return;
      }
      if (msg.kind === "row" && msg.data && !msg.data.error) {
        const dest = msg.data.destination;
        const prev = bestByDest.get(dest) || {};
        bestByDest.set(dest, { ...prev, ...msg.data });
        if (!hotelPhaseActive) {
          let extra = "";
          if (msg.data.destination_name) {
            const n = msg.data.destination_name;
            extra = ` · ${n.length > 40 ? `${n.slice(0, 40)}…` : n}`;
          }
          let h = "";
          if (msg.data.hotel_nightly_usd != null) {
            h = ` · hotel ~${Number(msg.data.hotel_nightly_usd).toFixed(0)} USD/nt`;
          }
          stEl.textContent = `Best so far: ${bestByDest.size} (${msg.data.destination} ${msg.data.price}${extra}${h})…`;
        }
        refreshFromMap();
      } else if (msg.kind === "row" && msg.data && msg.data.error) {
        if (!hotelPhaseActive) {
          stEl.textContent = `Error ${msg.data.destination}: ${msg.data.error.slice(0, 60)}…`;
        } else {
          refreshFromMap();
        }
      } else if (msg.kind === "miss") {
        const when = msg.departure_date ? ` on ${msg.departure_date}` : "";
        stEl.textContent = `No fare ${msg.destination}${when}…`;
      } else if (msg.kind === "day_start") {
        const r = msg.return_date ? ` · ret ${msg.return_date}` : "";
        stEl.textContent = `Scanning outbound ${msg.departure_date}${r}…`;
      } else if (msg.kind === "hotel_phase") {
        hotelPhaseActive = true;
        stEl.textContent = `Hotels 0/${msg.total} — starting Xotelo…`;
        stEl.classList.remove("muted");
      } else if (msg.kind === "hotel_progress") {
        const t = msg.total != null ? msg.total : "?";
        const d = msg.done != null ? msg.done : 0;
        const code = msg.destination ? ` · ${msg.destination}` : "";
        stEl.textContent = `Hotels ${d}/${t} (Xotelo)${code}…`;
        stEl.classList.remove("muted");
      } else if (msg.kind === "hotel_phase_done") {
        hotelPhaseActive = false;
      } else if (msg.kind === "done") {
        stEl.textContent = `Aggregated ${msg.count} destinations with prices.`;
      } else if (msg.kind === "complete") {
        streamFinishedOk = true;
        hotelPhaseActive = false;
        if (!scanHadFatalError) {
          stEl.textContent = `Done — ${bestByDest.size} destinations.`;
          stEl.classList.add("muted");
        }
        pBar.style.width = "100%";
        refreshFromMap();
      }
    }

    function parseSseBlock(block) {
      const lines = block.split("\n");
      const dataParts = [];
      for (const line of lines) {
        if (line.startsWith("data:")) {
          dataParts.push(line.slice(5).trimStart());
        }
      }
      if (dataParts.length) {
        handleEventPayload(dataParts.join("\n"));
      }
    }

    const ctrl = new AbortController();
    activeAbortController = ctrl;
    const { signal } = ctrl;

    (async () => {
      try {
        const res = await fetch(streamUrl, {
          signal,
          credentials: "same-origin",
          headers: { Accept: "text/event-stream" },
        });

        if (!res.ok) {
          let body = "";
          try {
            body = await res.text();
          } catch (_) {
            /* ignore */
          }
          let hint = "";
          if (res.status === 404) {
            hint =
              " If this is 404, restart from folder flight-explorer: python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 — then open http://127.0.0.1:8765/api/health (should list endpoints).";
          }
          stEl.textContent = `Server returned ${res.status}${body ? `: ${body.slice(0, 160)}` : ""}.${hint}`;
          stEl.classList.remove("muted");
          setBusy(false);
          if (activeAbortController === ctrl) activeAbortController = null;
          return;
        }

        const reader = res.body?.getReader();
        if (!reader) {
          stEl.textContent = "Streaming not supported in this browser.";
          setBusy(false);
          if (activeAbortController === ctrl) activeAbortController = null;
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let sep;
          while ((sep = buffer.indexOf("\n\n")) >= 0) {
            const rawEvent = buffer.slice(0, sep).trimEnd();
            buffer = buffer.slice(sep + 2);
            if (rawEvent) {
              parseSseBlock(rawEvent);
            }
          }
        }

        if (!streamFinishedOk && !signal.aborted) {
          stEl.textContent =
            "Connection closed before completion. Retry, or shorten horizon / check server logs.";
          stEl.classList.remove("muted");
        }
      } catch (err) {
        if (err.name === "AbortError") {
          return;
        }
        stEl.textContent = `Request failed: ${err.message}`;
        stEl.classList.remove("muted");
      } finally {
        if (activeAbortController === ctrl) {
          activeAbortController = null;
        }
        setBusy(false);
      }
    })();
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (activeAbortController) {
      activeAbortController.abort();
      activeAbortController = null;
    }

    bestByDest.clear();
    completed = 0;
    tbody.innerHTML = "";
    countBadge.textContent = "";
    chartNote.textContent = "";
    if (chart) {
      chart.destroy();
      chart = null;
    }

    const origin = originEl.value.trim().toUpperCase();
    const dateFrom = dateFromEl.value;
    const dateTo = dateToEl.value;
    const roundTrip = roundTripEl.checked;
    const tripDays = Number.parseInt(tripDaysEl.value, 10) || 7;
    const nonStop = nonStopEl.checked;
    const nonEuOnly = nonEuOnlyEl.checked;
    const excludeDomestic = excludeDomesticEl.checked;
    const excludeUk = excludeUkEl.checked;

    if (origin.length !== 3) {
      statusEl.textContent = "Origin must be a 3-letter IATA code.";
      return;
    }

    const nDays = daySpanInclusive(dateFrom, dateTo);
    if (nDays < 1) {
      statusEl.textContent = "Invalid date range.";
      return;
    }
    if (nDays > MAX_RANGE_DAYS) {
      statusEl.textContent = `Date range too long (max ${MAX_RANGE_DAYS} outbound days).`;
      return;
    }

    totalSteps = nDays * TOTAL_DESTINATIONS;

    setBusy(true);
    progressWrap.hidden = false;
    progressBar.style.width = "0%";
    statusEl.textContent = "Connecting…";
    statusEl.classList.remove("muted");
    calProgressWrap.hidden = true;
    quickProgressWrap.hidden = true;
    quickStatusEl.textContent = "";
    calStatusEl.textContent = "";

    const qs = new URLSearchParams({
      origin,
      date_from: dateFrom,
      date_to: dateTo,
      round_trip: roundTrip ? "true" : "false",
      trip_days: String(tripDays),
      non_stop: nonStop ? "true" : "false",
      non_eu_only: nonEuOnly ? "true" : "false",
      exclude_domestic: excludeDomestic ? "true" : "false",
      exclude_uk: excludeUk ? "true" : "false",
    });
    applyHotelParams(qs);

    const chartLabelBase = `${nDays} outbound day(s)${roundTrip ? " · round trip" : " · one-way"}`;
    runSseScan(apiUrl("/api/scan/stream", qs), chartLabelBase, statusEl, progressBar, progressWrap);
  });

  calendarForm.addEventListener("submit", (e) => {
    e.preventDefault();
    if (activeAbortController) {
      activeAbortController.abort();
      activeAbortController = null;
    }

    bestByDest.clear();
    completed = 0;
    tbody.innerHTML = "";
    countBadge.textContent = "";
    chartNote.textContent = "";
    if (chart) {
      chart.destroy();
      chart = null;
    }

    const origin = calOriginEl.value.trim().toUpperCase();
    const fromDate = calFromEl.value;
    const months = Number.parseInt(calMonthsEl.value, 10) || 6;
    const tripDays = Number.parseInt(calTripDaysEl.value, 10) || 7;
    const nonStop = calNonStopEl.checked;
    const nonEuOnly = calNonEuOnlyEl.checked;
    const excludeDomestic = calExcludeDomesticEl.checked;
    const excludeUk = calExcludeUkEl.checked;

    if (origin.length !== 3) {
      calStatusEl.textContent = "Origin must be a 3-letter IATA code.";
      return;
    }
    if (months < 1 || months > 12) {
      calStatusEl.textContent = "Months must be 1–12.";
      return;
    }

    totalSteps = TOTAL_DESTINATIONS;
    setBusy(true);
    calProgressWrap.hidden = false;
    calProgressBar.style.width = "0%";
    progressWrap.hidden = true;
    quickProgressWrap.hidden = true;
    calStatusEl.textContent = "Connecting (calendar API)…";
    calStatusEl.classList.remove("muted");
    quickStatusEl.textContent = "";
    statusEl.textContent = "";

    const qs = new URLSearchParams({
      origin,
      from_date: fromDate,
      months: String(months),
      trip_days: String(tripDays),
      non_stop: nonStop ? "true" : "false",
      non_eu_only: nonEuOnly ? "true" : "false",
      exclude_domestic: excludeDomestic ? "true" : "false",
      exclude_uk: excludeUk ? "true" : "false",
    });
    applyHotelParams(qs);
    const chartLabelBase = `Calendar A/R · ~${months} mo · ${tripDays}d trip`;
    runSseScan(apiUrl("/api/calendar/stream", qs), chartLabelBase, calStatusEl, calProgressBar, calProgressWrap);
  });
})();
