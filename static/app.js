/**
 * Property Tax Protest — Collin County, TX
 *
 * All data displayed on screen comes from the CCAD Socrata API via the
 * server-side /api/* endpoints.  No values are fabricated client-side.
 */

/* ── State ─────────────────────────────────────────────────────────────────── */
let selectedProperty = null;   // PropertyInfo object chosen by the user
let analysisReport   = null;   // ProtestReport returned by /api/analyze
let dataSource       = "";     // Caption shown below each section

/* ── Utility ────────────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);
const fmt   = n => n == null ? "N/A" : Number(n).toLocaleString("en-US");
const fmtUSD = n => n == null ? "N/A" : "$" + Number(n).toLocaleString("en-US", {minimumFractionDigits: 0, maximumFractionDigits: 0});
const fmtUSD2 = n => n == null ? "N/A" : "$" + Number(n).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});

function showError(containerId, msg) {
  const el = $(containerId);
  el.innerHTML = `<div class="error-msg">${msg}</div>`;
  el.classList.remove("hidden");
}

function setLoading(btnId, loading) {
  const btn = $(btnId);
  if (loading) {
    btn.disabled = true;
    btn.dataset.orig = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span> Loading…`;
  } else {
    btn.disabled = false;
    btn.innerHTML = btn.dataset.orig || btn.innerHTML;
  }
}

/* ── Step 1: Property Lookup ───────────────────────────────────────────────── */
$("search-form").addEventListener("submit", async e => {
  e.preventDefault();
  const address = $("address-input").value.trim();
  if (!address) return;

  $("lookup-error").classList.add("hidden");
  $("property-section").classList.add("hidden");
  $("analysis-section").classList.add("hidden");
  $("letter-section").classList.add("hidden");
  selectedProperty = null;
  analysisReport   = null;

  setLoading("search-btn", true);
  try {
    const res = await fetch("/api/lookup", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ address }),
    });

    const data = await res.json();
    if (!res.ok) {
      showError("lookup-error", data.detail || "Lookup failed.");
      return;
    }

    dataSource = data.data_source;

    if (data.matches.length === 1) {
      selectProperty(data.matches[0]);
    } else {
      renderMatchPicker(data.matches);
    }
  } catch (err) {
    showError("lookup-error", "Network error — could not reach the server.");
  } finally {
    setLoading("search-btn", false);
  }
});

function renderMatchPicker(matches) {
  const html = `
    <p style="margin-bottom:10px;font-size:.9rem;">
      Multiple properties matched — please select yours:
    </p>
    <div style="display:flex;flex-direction:column;gap:8px;">
      ${matches.map((m, i) => `
        <button class="btn-secondary" style="text-align:left;padding:10px 14px;"
                onclick="selectProperty(window._matches[${i}])">
          <strong>${m.address}</strong>${m.city ? ", " + m.city : ""}
          <span style="float:right;color:#888;font-size:.8rem;">
            ${fmtUSD(m.market_value)} | Acct ${m.account_num}
          </span>
        </button>`).join("")}
    </div>`;
  window._matches = matches;
  $("property-section").classList.remove("hidden");
  $("property-detail").innerHTML = html;
  $("analyze-row").classList.add("hidden");
  $("prop-source").textContent = dataSource;
}

function selectProperty(prop) {
  selectedProperty = prop;
  window._matches  = null;
  renderPropertyCard(prop);
  $("property-section").classList.remove("hidden");
  $("analysis-section").classList.add("hidden");
  $("letter-section").classList.add("hidden");
  analysisReport = null;
  // pre-fill tax rate input
  $("tax-rate").value = "1.80";
}

function renderPropertyCard(p) {
  const hasSqft = p.bldg_sqft && p.bldg_sqft > 0;
  const vpsf    = hasSqft ? (p.market_value / p.bldg_sqft).toFixed(2) : null;

  $("property-detail").innerHTML = `
    <div class="prop-grid">
      <div class="prop-item">
        <div class="label">Owner of Record</div>
        <div class="value">${p.owner_name || "N/A"}</div>
      </div>
      <div class="prop-item">
        <div class="label">Address</div>
        <div class="value">${p.address}${p.city ? ", " + p.city : ""}${p.zip_code ? " " + p.zip_code : ""}</div>
      </div>
      <div class="prop-item">
        <div class="label">CCAD Account #</div>
        <div class="value">${p.account_num}</div>
      </div>
      <div class="prop-item">
        <div class="label">Appraised Value</div>
        <div class="value money">${fmtUSD(p.market_value)}</div>
      </div>
      <div class="prop-item">
        <div class="label">Land Value</div>
        <div class="value">${p.land_value ? fmtUSD(p.land_value) : "N/A"}</div>
      </div>
      <div class="prop-item">
        <div class="label">Improvement Value</div>
        <div class="value">${p.improvement_value ? fmtUSD(p.improvement_value) : "N/A"}</div>
      </div>
      <div class="prop-item">
        <div class="label">Building Size</div>
        <div class="value">${hasSqft ? fmt(p.bldg_sqft) + " sqft" : "N/A"}</div>
      </div>
      <div class="prop-item">
        <div class="label">Year Built</div>
        <div class="value">${p.yr_built || "N/A"}</div>
      </div>
      <div class="prop-item">
        <div class="label">Neighborhood Code</div>
        <div class="value">${p.neighborhood_cd || "N/A"}</div>
      </div>
      <div class="prop-item">
        <div class="label">State Class</div>
        <div class="value">${p.state_class || "N/A"}</div>
      </div>
      ${vpsf ? `
      <div class="prop-item">
        <div class="label">Appraisal / sqft</div>
        <div class="value">${fmtUSD2(vpsf)}</div>
      </div>` : ""}
      <div class="prop-item">
        <div class="label">Data Year</div>
        <div class="value">${p.data_year || "N/A"}</div>
      </div>
    </div>`;

  $("analyze-row").classList.remove("hidden");
  $("prop-source").textContent = dataSource;
}

/* ── Step 2: Analysis ──────────────────────────────────────────────────────── */
$("analyze-btn").addEventListener("click", async () => {
  if (!selectedProperty) return;

  $("analysis-error").classList.add("hidden");
  $("analysis-section").classList.add("hidden");
  $("letter-section").classList.add("hidden");

  const taxRate = parseFloat($("tax-rate").value) || 1.8;

  setLoading("analyze-btn", true);
  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        account_num:       selectedProperty.account_num,
        neighborhood_cd:   selectedProperty.neighborhood_cd,
        bldg_sqft:         selectedProperty.bldg_sqft,
        yr_built:          selectedProperty.yr_built,
        market_value:      selectedProperty.market_value,
        effective_tax_rate: taxRate,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      showError("analysis-error", data.detail || "Analysis failed.");
      return;
    }

    analysisReport = data.report;
    renderAnalysis(data.report, data.data_source);
    $("analysis-section").classList.remove("hidden");
    $("analysis-section").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError("analysis-error", "Network error — could not reach the server.");
  } finally {
    setLoading("analyze-btn", false);
  }
});

function renderAnalysis(r, source) {
  // ── Verdict ──────────────────────────────────────────────────────────────
  let verdictHtml;
  if (r.protest_viable) {
    const pct = (((r.subject_value_per_sqft - r.median_comp_value_per_sqft) /
                   r.median_comp_value_per_sqft) * 100).toFixed(1);
    verdictHtml = `
      <div class="verdict bad">
        <div class="icon">⚠️</div>
        <div class="body">
          <h3>Overappraised — Protest Recommended</h3>
          <p>Your property is appraised <strong>${pct}% above</strong> the median
          of ${r.comps_count} comparable properties in the same CCAD neighborhood
          (${r.subject.neighborhood_cd}).  Under Texas Tax Code §41.43, this
          qualifies as <em>unequal appraisal</em>.</p>
        </div>
      </div>`;
  } else if (r.comps_count >= 5) {
    verdictHtml = `
      <div class="verdict good">
        <div class="icon">✅</div>
        <div class="body">
          <h3>Fairly Appraised</h3>
          <p>${r.protest_basis}</p>
        </div>
      </div>`;
  } else {
    verdictHtml = `
      <div class="verdict warn">
        <div class="icon">🔍</div>
        <div class="body">
          <h3>Insufficient Comparables</h3>
          <p>${r.protest_basis}</p>
        </div>
      </div>`;
  }

  // ── Savings boxes ─────────────────────────────────────────────────────────
  let savingsHtml = "";
  if (r.protest_viable) {
    savingsHtml = `
      <div class="savings-box">
        <div class="savings-item">
          <div class="s-label">Current Appraised Value</div>
          <div class="s-value">${fmtUSD(r.subject.market_value)}</div>
        </div>
        <div class="savings-item">
          <div class="s-label">Recommended Value</div>
          <div class="s-value">${fmtUSD(r.recommended_value)}</div>
        </div>
        <div class="savings-item">
          <div class="s-label">Potential Reduction</div>
          <div class="s-value">${fmtUSD(r.potential_reduction)}</div>
        </div>
        <div class="savings-item">
          <div class="s-label">Est. Annual Tax Savings</div>
          <div class="s-value">${fmtUSD(r.estimated_savings)}</div>
        </div>
      </div>
      <p style="font-size:.78rem;color:#666;">
        Savings estimated using your entered tax rate.
        Verify your exact combined rate on your Collin County tax bill.
      </p>`;
  }

  // ── $/sqft comparison ─────────────────────────────────────────────────────
  const vpsf = r.subject_value_per_sqft;
  const mvpsf = r.median_comp_value_per_sqft;
  let comparisonHtml = "";
  if (vpsf && mvpsf) {
    comparisonHtml = `
      <div style="margin:14px 0;background:#f7f9fb;border:1px solid #dde2ea;border-radius:8px;padding:14px 18px;">
        <div style="display:flex;gap:28px;flex-wrap:wrap;">
          <div>
            <div style="font-size:.75rem;color:#666;font-weight:600;">Subject $/sqft</div>
            <div style="font-size:1.3rem;font-weight:800;color:${r.protest_viable ? "#c0392b" : "#27ae60"}">
              ${fmtUSD2(vpsf)}
            </div>
          </div>
          <div style="align-self:center;font-size:1.5rem;color:#aaa;">vs.</div>
          <div>
            <div style="font-size:.75rem;color:#666;font-weight:600;">Median Comp $/sqft</div>
            <div style="font-size:1.3rem;font-weight:800;color:#0d4f96">${fmtUSD2(mvpsf)}</div>
          </div>
          <div>
            <div style="font-size:.75rem;color:#666;font-weight:600;">Mean Comp $/sqft</div>
            <div style="font-size:1.3rem;font-weight:800;color:#555">${fmtUSD2(r.mean_comp_value_per_sqft)}</div>
          </div>
          <div>
            <div style="font-size:.75rem;color:#666;font-weight:600;">Comparables used</div>
            <div style="font-size:1.3rem;font-weight:800;color:#555">${r.comps_count}</div>
          </div>
        </div>
      </div>`;
  }

  // ── Comps table ───────────────────────────────────────────────────────────
  let tableHtml = "";
  if (r.comps && r.comps.length > 0) {
    const subjectVpsf = r.subject_value_per_sqft;
    const rows = r.comps.slice(0, 30).map(c => {
      const cls = c.value_per_sqft > subjectVpsf ? "" :
                  c.value_per_sqft < subjectVpsf ? "vpsf-lo" : "";
      return `
        <tr>
          <td>${c.address}</td>
          <td>${fmt(c.bldg_sqft)}</td>
          <td>${c.yr_built || "N/A"}</td>
          <td>${fmtUSD(c.market_value)}</td>
          <td class="${cls}">${fmtUSD2(c.value_per_sqft)}</td>
        </tr>`;
    }).join("");

    // Subject row at top
    const subjectRow = `
      <tr class="subject-row">
        <td>${r.subject.address} (SUBJECT)</td>
        <td>${fmt(r.subject.bldg_sqft)}</td>
        <td>${r.subject.yr_built || "N/A"}</td>
        <td>${fmtUSD(r.subject.market_value)}</td>
        <td class="${r.protest_viable ? "vpsf-hi" : ""}">${fmtUSD2(subjectVpsf)}</td>
      </tr>`;

    tableHtml = `
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Address</th>
              <th>Sqft</th>
              <th>Yr Built</th>
              <th>Appraised Value</th>
              <th>$/sqft</th>
            </tr>
          </thead>
          <tbody>${subjectRow}${rows}</tbody>
        </table>
      </div>
      ${r.comps.length > 30 ? `<p style="font-size:.75rem;color:#888;margin-top:6px;">Showing 30 of ${r.comps.length} comparables.</p>` : ""}`;
  }

  $("analysis-content").innerHTML = `
    ${verdictHtml}
    ${savingsHtml}
    ${comparisonHtml}
    <h3 style="font-size:.9rem;font-weight:700;color:#0d2b52;margin:18px 0 6px;">
      Comparable Properties — CCAD Neighborhood ${r.subject.neighborhood_cd}
    </h3>
    ${tableHtml || "<p style='font-size:.88rem;color:#888;'>No comparables returned.</p>"}
    <p class="source-tag">${source}</p>`;

  // Show/hide letter section
  if (r.protest_viable) {
    $("letter-section").classList.remove("hidden");
  }
}

/* ── Step 3: Protest Letter ─────────────────────────────────────────────────── */
$("gen-letter-btn").addEventListener("click", async () => {
  if (!analysisReport) return;

  const contact = {
    date:  new Date().toLocaleDateString("en-US", {year:"numeric",month:"long",day:"numeric"}),
    name:  $("contact-name").value.trim()  || undefined,
    phone: $("contact-phone").value.trim() || undefined,
    email: $("contact-email").value.trim() || undefined,
  };

  setLoading("gen-letter-btn", true);
  try {
    const res = await fetch("/api/letter", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ report: analysisReport, contact }),
    });

    if (!res.ok) {
      const d = await res.json();
      showError("letter-error", d.detail || "Letter generation failed.");
      return;
    }

    const text = await res.text();
    $("letter-box").value = text;
    $("letter-output").classList.remove("hidden");
    $("letter-output").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    showError("letter-error", "Network error.");
  } finally {
    setLoading("gen-letter-btn", false);
  }
});

$("copy-letter-btn").addEventListener("click", () => {
  const ta = $("letter-box");
  ta.select();
  navigator.clipboard.writeText(ta.value).then(() => {
    $("copy-letter-btn").textContent = "Copied!";
    setTimeout(() => { $("copy-letter-btn").textContent = "Copy to Clipboard"; }, 2000);
  });
});

$("print-letter-btn").addEventListener("click", () => {
  const content = $("letter-box").value;
  const w = window.open("", "_blank");
  w.document.write(`<pre style="font-family:monospace;font-size:12pt;margin:40px;white-space:pre-wrap">${content}</pre>`);
  w.document.close();
  w.print();
});
