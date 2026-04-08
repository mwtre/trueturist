(function () {
  const TOTAL_STEPS = 181;
  /** Rough FX for display only when flight is EUR and hotel is USD (not live rates). */
  const INDICATIVE_EUR_USD = 1.085;

  const form = document.getElementById("user-form");
  const originSelect = document.getElementById("user-origin");
  const originCustomWrap = document.getElementById("user-origin-custom-wrap");
  const originCustom = document.getElementById("user-origin-custom");
  const monthEl = document.getElementById("user-month");
  const tripDaysEl = document.getElementById("user-trip-days");
  const regionEl = document.getElementById("user-region");
  const hotelOnlyEl = document.getElementById("user-hotel-only");
  const searchBtn = document.getElementById("user-search");
  const statusEl = document.getElementById("user-status");
  const progressWrap = document.getElementById("user-progress-wrap");
  const progressBar = document.getElementById("user-progress-bar");
  const resultsEl = document.getElementById("user-results");

  let activeAbort = null;
  let completedSteps = 0;
  /** @type {Map<string, object>} */
  const bestByDest = new Map();
  /** Origin IATA from the last successful search (for flight deep links). */
  let lastSearchOrigin = "";

  function defaultMonth() {
    const d = new Date();
    d.setMonth(d.getMonth() + 1);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    return `${y}-${m}`;
  }
  monthEl.value = defaultMonth();

  if (hotelOnlyEl) {
    hotelOnlyEl.addEventListener("change", () => {
      if (bestByDest.size) renderCards();
    });
  }

  originSelect.addEventListener("change", () => {
    const o = originSelect.value === "OTHER";
    originCustomWrap.classList.toggle("user-hidden", !o);
  });

  function getOrigin() {
    if (originSelect.value === "OTHER") {
      return originCustom.value.trim().toUpperCase();
    }
    return originSelect.value;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function nightCount(out, ret) {
    if (!out || !ret) return "—";
    const a = new Date(`${out}T12:00:00`).getTime();
    const b = new Date(`${ret}T12:00:00`).getTime();
    const n = Math.round((b - a) / 86400000);
    return n > 0 ? String(n) : "—";
  }

  function nightsBetween(out, ret) {
    if (!out || !ret) return 0;
    const a = new Date(`${out}T12:00:00`).getTime();
    const b = new Date(`${ret}T12:00:00`).getTime();
    const n = Math.round((b - a) / 86400000);
    return n > 0 ? n : 0;
  }

  function cardVisuals(r) {
    const cityUrl = r.city_image_url && String(r.city_image_url).startsWith("http") ? r.city_image_url : "";
    const hotelUrl = r.hotel_image_url && String(r.hotel_image_url).startsWith("http") ? r.hotel_image_url : "";
    const cityAlt = escapeHtml(`${r.destination} · city`);
    const hotelAlt = escapeHtml(r.hotel_sample_name || "Hotel");
    let html = '<div class="user-card-visual">';
    html += '<div class="user-card-visual-cell">';
    html += '<span class="user-card-img-label">City</span>';
    if (cityUrl) {
      html += `<img class="user-card-img" src="${escapeHtml(cityUrl)}" alt="${cityAlt}" width="280" height="158" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.style.display='none'; this.nextElementSibling.classList.remove('user-hidden')" />`;
      html += `<div class="user-card-img-fallback user-hidden" aria-hidden="true">${escapeHtml(r.destination)}</div>`;
    } else {
      html += `<div class="user-card-img-fallback" aria-hidden="true">${escapeHtml(r.destination)}</div>`;
    }
    html += "</div>";
    html += '<div class="user-card-visual-cell">';
    html += '<span class="user-card-img-label">Hotel</span>';
    if (hotelUrl) {
      html += `<img class="user-card-img" src="${escapeHtml(hotelUrl)}" alt="${hotelAlt}" width="280" height="158" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.style.display='none'; this.nextElementSibling.classList.remove('user-hidden')" />`;
      html += `<div class="user-card-img-fallback user-hidden" aria-hidden="true">—</div>`;
    } else {
      html += '<div class="user-card-img-fallback" aria-hidden="true">—</div>';
    }
    html += "</div></div>";
    return html;
  }

  function nonEurTotal(cur, _flight, _stayUsd, bits) {
    bits.push(
      `<li class="user-total-line"><strong>Totals</strong>: flight in ${escapeHtml(cur)}; hotel in USD — combine using your bank rate.</li>`
    );
  }

  /** TripAdvisor list metadata from Xotelo (richer context under hotel line). */
  function hotelListMetaHtml(r) {
    const lines = [];
    const lo = r.hotel_list_price_min != null ? Number(r.hotel_list_price_min) : null;
    const hi = r.hotel_list_price_max != null ? Number(r.hotel_list_price_max) : null;
    if (lo != null && hi != null) {
      lines.push(
        `TripAdvisor list guide ~${Math.round(lo)}–${Math.round(hi)} USD/night (not the live OTA floor)`
      );
    } else if (lo != null) {
      lines.push(`TripAdvisor list from ~${Math.round(lo)} USD/night`);
    } else if (hi != null) {
      lines.push(`TripAdvisor list up to ~${Math.round(hi)} USD/night`);
    }
    if (r.hotel_accommodation_type) {
      lines.push(escapeHtml(String(r.hotel_accommodation_type)));
    }
    if (r.hotel_labels) {
      lines.push(escapeHtml(String(r.hotel_labels)));
    }
    if (r.hotel_mentions) {
      lines.push(escapeHtml(String(r.hotel_mentions)));
    }
    const n = r.hotel_rates_checked != null ? Number(r.hotel_rates_checked) : null;
    if (n != null && n > 0) {
      lines.push(`Compared live rates across ${n.toLocaleString()} listings`);
    }
    if (!lines.length) return "";
    return `<span class="user-fineprint user-hotel-meta-detail">${lines.join("<br />")}</span>`;
  }

  function listGuideHeroSuffix(r) {
    return r.hotel_quote_source === "list_guide" ? " Hotel from TripAdvisor list (no live OTA)." : "";
  }

  /** Short suffix for card hero subtitle when hotel meta exists. */
  function hotelHeroSubExtra(r) {
    const parts = [];
    const n = r.hotel_rates_checked != null ? Number(r.hotel_rates_checked) : null;
    if (n != null && n > 0) {
      parts.push(`${n} listings checked for rates`);
    }
    const lo = r.hotel_list_price_min != null ? Number(r.hotel_list_price_min) : null;
    const hi = r.hotel_list_price_max != null ? Number(r.hotel_list_price_max) : null;
    if (lo != null && hi != null) {
      parts.push(`list ~${Math.round(lo)}–${Math.round(hi)} USD/nt`);
    }
    if (r.hotel_accommodation_type) {
      parts.push(escapeHtml(String(r.hotel_accommodation_type)));
    }
    return parts.length ? ` ${parts.join(" · ")}` : "";
  }

  /**
   * @param {object} r
   * @param {{ repeatCombinedEur?: boolean }} opts
   */
  function priceBreakdown(r, opts) {
    const repeatCombinedEur = opts && opts.repeatCombinedEur === true;
    const cur = (r.currency || "EUR").toUpperCase();
    const flight = Number(r.price);
    const stayUsd = r.hotel_stay_usd != null ? Number(r.hotel_stay_usd) : null;
    const nightly = r.hotel_nightly_usd != null ? Number(r.hotel_nightly_usd) : null;
    const nNights = nightsBetween(r.departure_date, r.return_date);
    const bits = [];

    bits.push(
      `<li><strong>Flight</strong> (return, 1 adult): ${flight.toFixed(0)} ${escapeHtml(cur)}</li>`
    );

    if (stayUsd != null && nightly != null) {
      const hn = r.hotel_sample_name ? escapeHtml(r.hotel_sample_name) : "Listing used for estimate";
      const ota = r.hotel_ota ? escapeHtml(r.hotel_ota) : "";
      const taParts = [];
      if (r.hotel_ta_rating != null) {
        taParts.push(`TripAdvisor ${Number(r.hotel_ta_rating).toFixed(1)}/5`);
      }
      if (r.hotel_ta_review_count != null) {
        taParts.push(`${Number(r.hotel_ta_review_count).toLocaleString()} reviews`);
      }
      const taBlock = taParts.length ? `<span class="user-card-ta">${taParts.join(" · ")}</span>` : "";
      const listGuideNote =
        r.hotel_quote_source === "list_guide"
          ? `<span class="user-fineprint">No live OTA rates for these dates; figure is from TripAdvisor list pricing (indicative).</span><br />`
          : "";
      const metaExtra = hotelListMetaHtml(r);
      bits.push(`<li><strong>Hotel</strong> (floor estimate): <em>${hn}</em>${taBlock}<br />
        ${listGuideNote}~${Math.round(nightly)} USD × ${nNights} nights = <strong>${Math.round(stayUsd)} USD</strong> stay${ota ? ` · ${ota}` : ""}${metaExtra ? `<br />${metaExtra}` : ""}</li>`);

      if (cur === "EUR" && repeatCombinedEur) {
        const hotelEurApprox = stayUsd / INDICATIVE_EUR_USD;
        const totalEur = flight + hotelEurApprox;
        bits.push(`<li class="user-total-line"><strong>Combined check</strong> ≈ <strong>${Math.round(totalEur)} EUR</strong>
          <span class="user-fineprint">USD→EUR @ 1 EUR ≈ ${INDICATIVE_EUR_USD} USD. Not a quote.</span></li>`);
      } else if (cur !== "EUR") {
        nonEurTotal(cur, flight, stayUsd, bits);
      }
    } else if (r.hotel_error) {
      bits.push(`<li class="user-hotel-miss"><strong>Hotel</strong>: ${escapeHtml(r.hotel_error)}</li>`);
    } else {
      bits.push(`<li class="muted"><strong>Hotel</strong>: not loaded yet or unavailable.</li>`);
    }

    return `<ul class="user-price-breakdown">${bits.join("")}</ul>`;
  }

  function cardHeroPricing(r) {
    const cur = (r.currency || "EUR").toUpperCase();
    const flight = Number(r.price);
    const stayUsd = r.hotel_stay_usd != null ? Number(r.hotel_stay_usd) : null;
    const nightly = r.hotel_nightly_usd != null ? Number(r.hotel_nightly_usd) : null;

    if (cur === "EUR" && stayUsd != null && nightly != null) {
      const hotelEurApprox = Math.round(stayUsd / INDICATIVE_EUR_USD);
      const totalEur = Math.round(flight + stayUsd / INDICATIVE_EUR_USD);
      const breakdown = `<ul class="user-card-hero-lines">
          <li class="user-card-hero-li"><span class="user-card-hero-k">Flight (return)</span><div class="user-card-hero-v"><strong>${flight.toFixed(
            0
          )} EUR</strong></div></li>
          <li class="user-card-hero-li"><span class="user-card-hero-k">Hotel (est. stay)</span><div class="user-card-hero-v"><strong>${Math.round(
            stayUsd
          )} USD</strong><span class="user-card-hero-approx">~${hotelEurApprox} EUR (hotel only @ 1 EUR ≈ ${INDICATIVE_EUR_USD} USD)</span></div></li>
        </ul>`;
      return {
        label: "Trip cost overview",
        breakdown,
        totalHeading: "Indicative total",
        main: `${totalEur} EUR`,
        mainPrefix: "≈",
        sub: `Sum of flight (EUR) + hotel stay converted from USD — rounded; not a quote.${listGuideHeroSuffix(r)}${hotelHeroSubExtra(r)}`,
        variant: "combined",
      };
    }

    if (stayUsd != null && nightly != null && cur !== "EUR") {
      const breakdown = `<ul class="user-card-hero-lines">
          <li class="user-card-hero-li"><span class="user-card-hero-k">Flight (return)</span><div class="user-card-hero-v"><strong>${flight.toFixed(
            0
          )} ${escapeHtml(cur)}</strong></div></li>
          <li class="user-card-hero-li"><span class="user-card-hero-k">Hotel (est. stay)</span><div class="user-card-hero-v"><strong>${Math.round(
            stayUsd
          )} USD</strong></div></li>
        </ul>`;
      return {
        label: "Trip cost overview",
        breakdown,
        totalHeading: "No single-currency total",
        main: `${flight.toFixed(0)} ${cur} + ${Math.round(stayUsd)} USD`,
        mainPrefix: "",
        sub: `Open details to interpret mixed currencies.${listGuideHeroSuffix(r)}${hotelHeroSubExtra(r)}`,
        variant: "mixed",
      };
    }

    if (r.hotel_error) {
      return {
        label: "Flight (return)",
        breakdown: "",
        totalHeading: "",
        main: `${flight.toFixed(0)} ${cur}`,
        mainPrefix: "",
        sub: `Hotel estimate: ${escapeHtml(r.hotel_error)}`,
        variant: "flight-hotel-err",
      };
    }

    return {
      label: "Flight (return)",
      breakdown: "",
      totalHeading: "",
      main: `${flight.toFixed(0)} ${cur}`,
      mainPrefix: "",
      sub: "Hotel total will appear here when loaded",
      variant: "flight-only",
    };
  }

  /** Only show trips where Xotelo returned a usable hotel floor (exclude failures / not enriched). */
  function rowHasHotelEstimate(r) {
    return (
      r.hotel_nightly_usd != null &&
      r.hotel_stay_usd != null &&
      !r.hotel_error
    );
  }

  /** TripAdvisor traveler “bubble” as ★/☆ + score (not official hotel star class). */
  function taStarsBlock(r) {
    const rating = r.hotel_ta_rating;
    if (rating == null || rating === "" || Number.isNaN(Number(rating))) {
      const na =
        '<span class="user-card-stars-na" title="No TripAdvisor rating for this listing">—</span>';
      return `<div class="user-card-stars user-card-stars--empty"><span class="user-card-stars-heading">Hotel</span>${na}</div>`;
    }
    const x = Math.max(0, Math.min(5, Number(rating)));
    const filled = Math.min(5, Math.max(0, Math.round(x)));
    let inner = "";
    for (let i = 0; i < 5; i++) {
      const on = i < filled;
      inner += `<span class="user-star ${on ? "user-star--on" : "user-star--off"}" aria-hidden="true">${on ? "★" : "☆"}</span>`;
    }
    const aria = `TripAdvisor rating ${x.toFixed(1)} out of 5`;
    let reviews = "";
    if (r.hotel_ta_review_count != null && Number(r.hotel_ta_review_count) > 0) {
      reviews = `<span class="user-card-stars-reviews" aria-hidden="true">(${Number(
        r.hotel_ta_review_count
      ).toLocaleString()} reviews)</span>`;
    }
    return `<div class="user-card-stars" role="img" aria-label="${escapeHtml(aria)}">
      <span class="user-card-stars-heading">Hotel</span>
      <span class="user-card-stars-inner">${inner}</span>
      <span class="user-card-stars-num">${x.toFixed(1)}</span>${reviews}
    </div>`;
  }

  /** ISO 3166-1 alpha-2 → regional-indicator flag emoji. */
  function isoToFlagEmoji(cc) {
    if (!cc || typeof cc !== "string") return "";
    const u = cc.toUpperCase().trim();
    if (u.length !== 2) return "";
    const a = 65;
    const c0 = u.charCodeAt(0);
    const c1 = u.charCodeAt(1);
    if (c0 < a || c0 > 90 || c1 < a || c1 > 90) return "";
    return String.fromCodePoint(0x1f1e6 + (c0 - a), 0x1f1e6 + (c1 - a));
  }

  function cardFlagHtml(r) {
    const cc = (r.destination_country_code || "").trim();
    const emoji = isoToFlagEmoji(cc);
    if (!emoji) return "";
    const label = `Country ${cc}`;
    return `<span class="user-card-flag" role="img" aria-label="${escapeHtml(label)}" title="${escapeHtml(
      cc
    )}">${emoji}</span>`;
  }

  function cardLocationHeader(r, cardId) {
    const place = escapeHtml(r.destination_name || r.destination);
    const iata = escapeHtml(r.destination);
    return `<header class="user-card-head">
      <div class="user-card-head-text">
        <h2 class="user-card-place" id="${cardId}-title"><span class="user-card-place-inner">${cardFlagHtml(
          r
        )}<span class="user-card-place-text">${place}</span></span></h2>
        <div class="user-card-head-row">
          <p class="user-card-iata"><span class="user-card-iata-code">${iata}</span></p>
          ${taStarsBlock(r)}
        </div>
      </div>
    </header>`;
  }

  function cardTripFacts(r) {
    const parts = [];
    const n = nightsBetween(r.departure_date, r.return_date);
    if (Number(n) > 0) {
      parts.push(`${n} nights`);
    }
    const stops = r.stops;
    if (typeof stops === "number" && stops >= 0) {
      parts.push(stops === 0 ? "Non-stop (total)" : `${stops} stop${stops === 1 ? "" : "s"} (total)`);
    }
    const dur = r.duration_minutes;
    if (typeof dur === "number" && dur > 0) {
      const h = Math.floor(dur / 60);
      const m = dur % 60;
      parts.push(`~${h}h ${String(m).padStart(2, "0")}m air time`);
    }
    if (!parts.length) {
      return "";
    }
    return `<p class="user-card-facts">${escapeHtml(parts.join(" · "))}</p>`;
  }

  function cardScheduleLines(r) {
    const out = (r.outbound_times_local || "").trim();
    const inn = (r.inbound_times_local || "").trim();
    if (!out && !inn) {
      return "";
    }
    const bits = [];
    if (out) {
      bits.push(`Out (local) ${escapeHtml(out)}`);
    }
    if (inn) {
      bits.push(`Back (local) ${escapeHtml(inn)}`);
    }
    return `<p class="user-card-schedule">${bits.join("<br />")}</p>`;
  }

  function cardDestinationBlurb(r) {
    const b = (r.destination_blurb || "").trim();
    const wiki =
      r.destination_wiki_url && String(r.destination_wiki_url).startsWith("http")
        ? String(r.destination_wiki_url)
        : "";
    if (!b && !wiki) {
      return "";
    }
    const para = b ? `<span class="user-card-blurb-text">${escapeHtml(b)}</span>` : "";
    const link = wiki
      ? `<a class="user-card-wiki-link" href="${escapeHtml(wiki)}" target="_blank" rel="noopener noreferrer">Wikipedia</a>`
      : "";
    const gap = para && link ? " " : "";
    return `<div class="user-card-blurb">${para}${gap}${link}</div>`;
  }

  function googleFlightsRoundTripUrl(originIata, destIata, outIso, inIso) {
    const o = (originIata || "").toUpperCase();
    const d = (destIata || "").toUpperCase();
    const q = `Roundtrip flights from ${o} to ${d} on ${outIso} returning ${inIso}`;
    return `https://www.google.com/travel/flights?q=${encodeURIComponent(q)}`;
  }

  function googleHotelsUrl(placeLabel, checkin, checkout) {
    const q = `hotels in ${placeLabel} check in ${checkin} check out ${checkout}`;
    return `https://www.google.com/travel/hotels?q=${encodeURIComponent(q)}`;
  }

  function cardBookingLinks(r) {
    const dest = (r.destination || "").trim().toUpperCase();
    const out = (r.departure_date || "").trim();
    const inn = (r.return_date || "").trim();
    if (!dest || out.length < 10 || inn.length < 10) {
      return "";
    }
    const origin = (lastSearchOrigin || "").trim().toUpperCase();
    const flightHref =
      origin.length === 3
        ? googleFlightsRoundTripUrl(origin, dest, out, inn)
        : `https://www.google.com/travel/flights?q=${encodeURIComponent(
            `Roundtrip flights to ${dest} on ${out} returning ${inn}`
          )}`;
    let hotelPlace = (r.destination_name || "").trim();
    if (hotelPlace) {
      hotelPlace = hotelPlace.replace(/\s+(International\s+)?Airport\s*$/i, "").trim();
      if (hotelPlace.includes(",")) {
        hotelPlace = hotelPlace.split(",")[0].trim();
      }
    }
    if (!hotelPlace) {
      hotelPlace = dest;
    }
    const hotelHref = googleHotelsUrl(hotelPlace, out, inn);
    return `<div class="user-card-booking" role="navigation" aria-label="Search booking sites">
      <a class="user-card-book-link user-card-book-link--flight" href="${escapeHtml(flightHref)}" target="_blank" rel="noopener noreferrer" title="Open Google Flights in a new tab">Search flights</a>
      <a class="user-card-book-link user-card-book-link--hotel" href="${escapeHtml(hotelHref)}" target="_blank" rel="noopener noreferrer" title="Open Google Hotels in a new tab">Search hotels</a>
      <span class="user-card-book-hint">Google Travel — prices may differ from this scan.</span>
    </div>`;
  }

  /** Sort by combined trip cost in EUR-equivalent (hotel required for visible cards). */
  function combinedTripSortKey(r) {
    const flight = Number(r.price);
    const stay = Number(r.hotel_stay_usd);
    return flight + stay / INDICATIVE_EUR_USD;
  }

  /** Hotel-backed rows first (by indicative combined cost), then flight-only (by fare). */
  function tripDisplaySort(a, b) {
    const ha = rowHasHotelEstimate(a);
    const hb = rowHasHotelEstimate(b);
    if (ha !== hb) {
      return ha ? -1 : 1;
    }
    if (ha && hb) {
      const d = combinedTripSortKey(a) - combinedTripSortKey(b);
      if (d !== 0) return d;
      return a.destination.localeCompare(b.destination);
    }
    const fa = Number(a.price);
    const fb = Number(b.price);
    if (fa !== fb) return fa - fb;
    return a.destination.localeCompare(b.destination);
  }

  function renderCards() {
    const allFlightOk = Array.from(bestByDest.values()).filter((r) => !r.error);
    const onlyHotel = hotelOnlyEl && hotelOnlyEl.checked;
    let rows = onlyHotel ? allFlightOk.filter(rowHasHotelEstimate) : allFlightOk.slice();
    rows.sort(tripDisplaySort);
    if (!rows.length) {
      if (allFlightOk.length) {
        resultsEl.innerHTML = onlyHotel
          ? '<p class="user-empty">No trips with a hotel estimate match — try unchecking “flight-only” or wait for enrichment to finish.</p>'
          : '<p class="user-empty">No fares for this search. Try another month or origin.</p>';
      } else {
        resultsEl.innerHTML =
          '<p class="user-empty">No fares yet. Try another month or origin.</p>';
      }
      return;
    }
    const uid = `uc-${Date.now()}`;
    resultsEl.innerHTML = rows
      .map((r, idx) => {
        const nights = nightCount(r.departure_date, r.return_date);
        const hero = cardHeroPricing(r);
        const cardId = `${uid}-${idx}`;
        return `<article class="user-card" data-variant="${hero.variant}" aria-labelledby="${cardId}-title">
          ${cardVisuals(r)}
          <div class="user-card-body">
            ${cardLocationHeader(r, cardId)}
            ${cardTripFacts(r)}
            ${cardScheduleLines(r)}
            ${cardDestinationBlurb(r)}
            <div class="user-card-hero-price">
              <span class="user-card-hero-label">${escapeHtml(hero.label)}</span>
              ${hero.breakdown || ""}
              ${hero.totalHeading ? `<p class="user-card-hero-total-heading">${escapeHtml(hero.totalHeading)}</p>` : ""}
              <p class="user-card-hero-amount">
                ${hero.mainPrefix ? `<span class="user-card-hero-prefix">${escapeHtml(hero.mainPrefix)}</span> ` : ""}<span class="user-card-hero-value">${escapeHtml(hero.main)}</span>
              </p>
              <p class="user-card-hero-sub">${hero.sub}</p>
            </div>
            <div class="user-card-meta">
              <p class="user-card-dates">
                <strong>Out</strong> ${escapeHtml(r.departure_date || "—")} →
                <strong>Back</strong> ${escapeHtml(r.return_date || "—")}
                <span class="muted"> · ${nights} nights</span>
              </p>
              ${cardBookingLinks(r)}
            </div>
            <details class="user-card-details">
              <summary class="user-card-summary"><span>Price & trip details</span><span class="user-card-chevron" aria-hidden="true"></span></summary>
              <div class="user-card-details-inner">
                ${priceBreakdown(r, { repeatCombinedEur: false })}
                <p class="user-card-note">Indicative — confirm on airline & hotel sites before paying.</p>
              </div>
            </details>
          </div>
        </article>`;
      })
      .join("");
  }

  function setBusy(busy) {
    searchBtn.disabled = busy;
  }

  function apiUrl(path, qs) {
    const u = new URL(path, window.location.origin);
    u.search = qs.toString();
    return u.toString();
  }

  function parseSseBlock(block, handler) {
    const lines = block.split("\n");
    const dataParts = [];
    for (const line of lines) {
      if (line.startsWith("data:")) {
        dataParts.push(line.slice(5).trimStart());
      }
    }
    if (dataParts.length) {
      handler(dataParts.join("\n"));
    }
  }

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const origin = getOrigin();
    if (origin.length !== 3) {
      statusEl.textContent = "Please enter a 3-letter airport code.";
      statusEl.classList.remove("muted");
      return;
    }

    const ym = monthEl.value;
    if (!ym || ym.length < 7) {
      statusEl.textContent = "Choose a month.";
      statusEl.classList.remove("muted");
      return;
    }

    if (activeAbort) {
      activeAbort.abort();
      activeAbort = null;
    }

    bestByDest.clear();
    completedSteps = 0;
    resultsEl.innerHTML = "";
    progressBar.style.width = "0%";
    progressWrap.classList.remove("user-hidden");
    statusEl.classList.remove("muted");
    statusEl.textContent = "Searching…";
    setBusy(true);
    lastSearchOrigin = origin;

    const fromDate = `${ym}-01`;
    const tripDays = tripDaysEl.value || "7";
    const region = regionEl.value;
    const euOnly = region === "eu" ? "true" : "false";

    const qs = new URLSearchParams({
      origin,
      from_date: fromDate,
      months: "1",
      trip_days: tripDays,
      non_stop: "false",
      non_eu_only: "false",
      eu_only: euOnly,
      exclude_domestic: "false",
      exclude_uk: "false",
      with_hotels: "true",
      hotel_top_n: "28",
      hotel_five_star: "false",
      hotel_workers: "6",
      concurrency: "8",
    });

    const streamUrl = apiUrl("/api/calendar/stream", qs);

    let hotelPhaseActive = false;
    let streamOk = false;

    function handlePayload(text) {
      let msg;
      try {
        msg = JSON.parse(text);
      } catch {
        statusEl.textContent = "Bad response from server.";
        return;
      }

      if (msg.kind === "progress") {
        completedSteps = Math.min(completedSteps + 1, TOTAL_STEPS);
        progressBar.style.width = `${Math.round((completedSteps / TOTAL_STEPS) * 100)}%`;
        if (!hotelPhaseActive) {
          statusEl.textContent = `Scanning destinations… ${completedSteps}/${TOTAL_STEPS}`;
        }
        return;
      }

      if (msg.kind === "error" && msg.detail) {
        statusEl.textContent = `Error: ${msg.detail}`;
        return;
      }

      if (msg.kind === "row" && msg.data && !msg.data.error) {
        const dest = msg.data.destination;
        const prev = bestByDest.get(dest) || {};
        bestByDest.set(dest, { ...prev, ...msg.data });
        if (!hotelPhaseActive) {
          statusEl.textContent = `Best prices so far: ${bestByDest.size} destinations`;
        }
        renderCards();
        return;
      }

      if (msg.kind === "hotel_phase") {
        hotelPhaseActive = true;
        statusEl.textContent = `Hotels 0/${msg.total} — checking rates…`;
        return;
      }

      if (msg.kind === "hotel_progress") {
        const t = msg.total != null ? msg.total : "?";
        const d = msg.done != null ? msg.done : 0;
        const code = msg.destination ? ` · ${msg.destination}` : "";
        statusEl.textContent = `Hotels ${d}/${t}${code}…`;
        return;
      }

      if (msg.kind === "hotel_phase_done") {
        hotelPhaseActive = false;
        renderCards();
        return;
      }

      if (msg.kind === "complete") {
        streamOk = true;
        hotelPhaseActive = false;
        progressBar.style.width = "100%";
        statusEl.textContent = `Done — ${bestByDest.size} destinations with prices.`;
        statusEl.classList.add("muted");
        renderCards();
      }
    }

    const ctrl = new AbortController();
    activeAbort = ctrl;

    (async () => {
      try {
        const res = await fetch(streamUrl, {
          signal: ctrl.signal,
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
          statusEl.textContent = `Server error ${res.status}${body ? `: ${body.slice(0, 120)}` : ""}`;
          statusEl.classList.remove("muted");
          return;
        }

        const reader = res.body?.getReader();
        if (!reader) {
          statusEl.textContent = "Your browser does not support streaming.";
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
            const raw = buffer.slice(0, sep).trimEnd();
            buffer = buffer.slice(sep + 2);
            if (raw) parseSseBlock(raw, handlePayload);
          }
        }

        if (!streamOk && !ctrl.signal.aborted) {
          statusEl.textContent = "Connection ended early. Try again.";
          statusEl.classList.remove("muted");
        }
      } catch (err) {
        if (err.name !== "AbortError") {
          statusEl.textContent = `Request failed: ${err.message}`;
          statusEl.classList.remove("muted");
        }
      } finally {
        activeAbort = null;
        setBusy(false);
      }
    })();
  });
})();
