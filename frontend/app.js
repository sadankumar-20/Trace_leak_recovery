const $ = (s) => document.querySelector(s);
const rupee = (p) => "Rs." + (p / 100).toLocaleString("en-IN",
  {maximumFractionDigits: 0});
const api = (u, o) => fetch(u, o).then(async (r) => {
  const j = await r.json();
  if (!r.ok) throw j;
  return j;
});
const ROLE = "executor";   // demo role; the API enforces it server-side
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- animated numbers (real values only) ---------- */
function countUp(el, target, fmt) {
  if (REDUCED) { el.textContent = fmt(target); return; }
  const t0 = performance.now(), dur = 900;
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur);
    el.textContent = fmt(Math.round(target * (1 - Math.pow(1 - k, 3))));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}
const observe = (els, cls) => {
  const io = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) { e.target.classList.add(cls); io.unobserve(
      e.target); e.target.dispatchEvent(new Event("revealed")); }
  }), { threshold: 0.35 });
  els.forEach((el) => io.observe(el));
};

/* ---------- the Overview story: ten beats, real numbers ---------- */
async function story() {
  const [k, ev, ex] = await Promise.all([
    api("/kpis"), api("/evaluation"), api("/exceptions")]);
  const r = ev.result;
  const sample = ex.exceptions.find((e) =>
    e.type === "missing_settlement") || ex.exceptions[0];
  const BEATS = [
    ["THE QUIET PROBLEM", `Money appears correct.`],
    ["THREE LEDGERS", `Then the order book, the gateway and the bank
      disagree — <b class="num">${rupee(k.leakage_found_paise)}</b> of
      leakage hidden inside a 5,000-order quarter.`],
    ["THE BROKEN EDGE", `Trace finds it deterministically: ${sample.order.id}
      settled at the gateway, and the bank never posted the UTR — a broken
      edge in the evidence graph, <b class="num">${rupee(Math.abs(
      sample.delta_paise))}</b> short.`],
    ["AI INVESTIGATES", `A bounded investigator reads only what the tools
      return, and proposes a hypothesis — labeled untrusted.`],
    ["SYSTEMS PROVE", `Deterministic validation recomputes every claim to
      the paisa. The AI was wrong <b class="num">${r.variant_b.errors}</b>
      times on held-out. Errors that escaped:
      <b class="num">${r.variant_b.escaped}</b>.`],
    ["POLICY DECIDES", `Eight gates and counterparty economics:
      <b class="num">${r.variant_c.packages}</b> claims filed,
      <b class="num">${r.variant_c.write_off}</b> written off because
      pursuing them costs more than they return,
      <b class="num">${r.variant_c.escalate}</b> sent to humans.`],
    ["EXECUTOR ACTS", `One idempotent execution per exception — ever.
      Double executions so far:
      <b class="num">${k.double_executions}</b>.`],
    ["MONEY RETURNS", `Actual recovery, verified against the ledger:
      <b class="num">${rupee(k.recovered_paise)}</b> gross,
      <b class="num">${rupee(k.net_recovered_paise)}</b> net.`],
    ["PATTERNS EMERGE", `Exceptions cluster into systemic root causes —
      confirmed only when they survive deterministic challenge.`],
    ["PREVENTION", `Fixing the causes is worth an
      <span class="est">estimated
      <b class="num">${rupee(k.estimated_preventable_paise)}</b></span>
      in future leakage — labeled ESTIMATED, never added to actual
      recovery.`]];
  $("#story").innerHTML = BEATS.map(([kick, text], i) => `
    <div class="beat"><div class="card-story">
      <span class="chapter">${String(i + 1).padStart(2, "0")}</span>
      <span class="kick">${kick}</span><p>${wordize(text)}</p>
      <div class="rulebar"></div>
    </div></div>`).join("");
  $("#rail").innerHTML = BEATS.map(() => "<i></i>").join("");
  const dots = [...document.querySelectorAll("#rail i")];
  new IntersectionObserver((es) => es.forEach((e) => {
    const idx = [...document.querySelectorAll(".beat")]
      .indexOf(e.target);
    if (e.isIntersecting) dots.forEach((d, j) =>
      d.classList.toggle("on", j === idx));
  }), { threshold: 0.6 }).observe
    ? [...document.querySelectorAll(".beat")].forEach((b) =>
      new IntersectionObserver((es) => es.forEach((e) => {
        if (e.isIntersecting) {
          const idx = [...document.querySelectorAll(".beat")]
            .indexOf(e.target);
          dots.forEach((d, j) => d.classList.toggle("on", j === idx));
        }
      }), { threshold: 0.6 }).observe(b)) : null;
  document.querySelectorAll(".beat").forEach((b, i) => {
    b.querySelectorAll(".w").forEach((w, j) =>
      w.style.transitionDelay = REDUCED ? "0s" : `${j * 28}ms`);
  });
  observe([...document.querySelectorAll(".beat")], "on");
}
function wordize(html) {
  // wrap plain words in reveal spans; keep tags intact
  return html.split(/(<[^>]+>)/g).map((part) =>
    part.startsWith("<") ? part :
    part.split(/\s+/).filter(Boolean).map((w) =>
      `<span class="w">${w}</span>`).join(" ")).join(" ");
}

/* ---------- KPI wall (count-up from real values) ---------- */
async function kpis() {
  const k = await api("/kpis");
  const T = [[k.leakage_found_paise, "leakage found", "OBSERVED"],
    [k.claimed_paise, "claimed", "VERIFIED"],
    [k.recovered_paise, "recovered", k.labels.recovered],
    [k.net_recovered_paise, "net recovered", "ACTUAL"],
    [k.written_off_paise, "written off", "STOPPING RULE"],
    [k.estimated_preventable_paise, "prevented future loss",
     k.labels.preventable, true]];
  $("#kpis").innerHTML = T.map(([v, kk, tag, est], i) =>
    `<div class="kpi ${est ? "est" : ""}" data-v="${v}">
      <div class="v">Rs.0</div><div class="k">${kk}</div>
      <div class="tag">${tag}</div></div>`).join("");
  const tiles = [...document.querySelectorAll(".kpi")];
  tiles.forEach((t) => t.addEventListener("revealed", () =>
    countUp(t.querySelector(".v"), +t.dataset.v, rupee)));
  observe(tiles, "on");
}

/* ---------- case-card grid (replaces the old table) ---------- */
let ALL_CASES = [], FILTER = "all", QUERY = "";
async function reconTable() {
  ALL_CASES = (await api("/exceptions")).exceptions;
  const types = [...new Set(ALL_CASES.map((e) => e.type))].sort();
  $("#filters").innerHTML = ["all", ...types].map((tp) =>
    `<button data-f="${tp}" class="${tp === FILTER ? "on" : ""}">
     ${tp}</button>`).join("");
  document.querySelectorAll("#filters button").forEach((b) =>
    b.addEventListener("click", () => { FILTER = b.dataset.f;
      reconTable(); }));
  $("#search").oninput = (ev) => { QUERY = ev.target.value.toLowerCase();
    drawCards(); };
  drawCards();
}
function drawCards() {
  const rows = ALL_CASES.filter((e) =>
    (FILTER === "all" || e.type === FILTER)
    && (!QUERY || `${e.order.id} ${e.exception_id} ${e.type}
        ${e.decision}`.toLowerCase().includes(QUERY)));
  $("#cards").innerHTML = rows.map((e) => `
    <div class="case" data-id="${e.exception_id}">
      <div class="head"><span class="oid">${e.order.id}</span>
        <span class="delta">\u2212${rupee(Math.abs(e.delta_paise))}</span>
      </div>
      <div class="ledger3">
        <div><b>ORDER</b>${e.order.id}</div>
        <div><b>${e.gateway.gw}</b>${rupee(e.gateway.amount_paise)}</div>
        <div class="short"><b>BANK</b>${rupee(e.bank.expected_paise)}
          \u2192 ${rupee(e.bank.actual_paise)}</div>
      </div>
      <div class="foot"><span class="chip type">${e.type}</span>
        <span class="chip warn">${e.decision}</span>
        <span class="chip ok">${e.state}</span></div>
    </div>`).join("") || "<p class='mono'>no cases match</p>";
  document.querySelectorAll(".case").forEach((c) =>
    c.addEventListener("click", () => detail(c.dataset.id)));
}

/* ---------- detail: interactive graph, animated gates, timeline ------- */
async function detail(id) {
  const d = await api("/exceptions/" + id);
  const g = d.evidence_graph;
  const gates = d.admissibility ? Object.entries(
    d.admissibility.gate_results).map(([k, v], i) =>
    `<div class="gate" style="transition-delay:${REDUCED ? 0 : i * 90}ms">
      <span>${k}</span><span class="g-${v}">${v}</span></div>`).join("")
    : "<em>no gate run (verdict not supported)</em>";
  const STEPS = ["EXCEPTION", "INVESTIGATE", "PROVE", "GATES",
                 "DECIDE", "EXECUTE", "RECOVER", "AUDIT"];
  const hit = new Set(["EXCEPTION", "INVESTIGATE", "PROVE", "GATES",
                       "DECIDE"]);
  if (d.execution) { hit.add("EXECUTE"); hit.add("AUDIT"); }
  if (d.recovery) hit.add("RECOVER");
  const ov = $("#overlay");
  ov.hidden = false;
  document.body.style.overflow = "hidden";
  ov.innerHTML = `<div class="file">
   <div class="rail2">${STEPS.map((s) =>
     `<div class="step ${hit.has(s) ? "hit" : ""}">${s}</div>`).join("")}
   </div><div class="body">
   <button class="close" id="closeov">CLOSE \u2715</button>
   <h2>${id}</h2>
   <p class="sub">${d.discrepancy.discrepancy_type} \u00b7
       \u0394 ${rupee(Math.abs(d.discrepancy.delta_paise))} \u00b7
       deadline ${d.discrepancy.claim_deadline}</p>
   <div class="cols">
    <div class="card"><h3>EVIDENCE GRAPH (${Object.keys(g.nodes).length}
      hash-verified nodes \u2014 click a node to trace its edges)</h3>
      ${Object.values(g.nodes).map((n) => `<div class="node"
        data-node="${n.id}">${n.table} \u00b7 ${n.id}<br>
        ${n.amount_paise != null ? rupee(n.amount_paise) : ""}
        <span class="lineage">${n.record_hash.slice(0, 10)}\u2026</span>
        </div>`).join("")}
      ${g.edges.map((e) => `<div class="edge ${e.broken ? "broken" : ""}"
        data-src="${e.src}" data-dst="${e.dst || ""}">
        ${e.src} \u2500${e.type}\u2192 ${e.dst || "\u2718 MISSING"}
        </div>`).join("")}</div>
    <div class="card"><h3>AI INVESTIGATION</h3>
      <div class="unverified">${d.ai.hypothesis.label}:
        <b>${d.ai.hypothesis.type}</b>
        (${rupee(d.ai.hypothesis.amount_paise)})</div>
      <p class="mono">tools: ${d.ai.tools_used.join(" \u2192 ")}</p>
      <p class="mono">verdict: <b>${d.ai.verdict}</b></p></div>
    <div class="card gates"><h3>ADMISSIBILITY \u2014 8 GATES</h3>
      ${gates}</div>
    <div class="card"><h3>DECISION &amp; ECONOMICS</h3>
      <p><b>${d.decision.selected_action}</b></p>
      <p class="mono">${d.decision.reason}</p>
      ${Object.entries(d.decision.rejected_actions || {}).map(([a, r]) =>
        `<p class="mono">\u2717 ${a}: ${r}</p>`).join("")}</div>
    <div class="card"><h3>EXECUTION &amp; RECOVERY (idempotent)</h3>
      ${d.execution ? `<p class="mono">${d.execution.execution_id} \u00b7
        <span class="chip ${d.execution.execution_status}">
        ${d.execution.execution_status}</span> \u00b7 attempts
        ${d.execution.attempt_count} \u00b7 idempotency key =
        exception id</p>` : "<p>none</p>"}
      ${d.recovery ? `<p class="mono">recovered
        ${rupee(d.recovery.recovered_paise)} \u00b7 net
        ${rupee(d.recovery.net_recovery_paise)} \u00b7 ref
        ${d.recovery.counterparty_reference}</p>` : ""}</div>
    <div class="card"><h3>INVESTIGATION TIMELINE
      (${d.audit.length} audit events)</h3>
      <ul class="tl">${d.audit.slice(-8).map((e) =>
        `<li>#${e.seq} \u00b7 ${e.event_type}</li>`).join("")}</ul>
      <p class="mono">case state: ${d.case.state}</p></div>
   </div>
   <div class="actions">${Object.entries(d.allowed_actions).map(([a, i]) =>
     `<button class="btn" data-act="${a}" ${i.enabled ? "" : "disabled"}
       title="${i.reason.replace(/"/g, "'")}">${a}</button>`).join("")}
   </div>
   <p class="mono">disabled actions show the machine reason on hover \u2014
     enforcement is server-side, the UI only reflects it</p>
   </div></div>`;
  $("#closeov").addEventListener("click", () => {
    ov.hidden = true; document.body.style.overflow = ""; });
  ov.addEventListener("click", (e) => { if (e.target === ov) {
    ov.hidden = true; document.body.style.overflow = ""; } });
  requestAnimationFrame(() =>
    ov.querySelector(".gates").classList.add("gates-on"));
  document.querySelectorAll(".node").forEach((n) =>
    n.addEventListener("click", () => {
      const id = n.dataset.node;
      const sel = n.classList.toggle("sel");
      document.querySelectorAll(".node").forEach((m) =>
        m !== n && m.classList.remove("sel"));
      document.querySelectorAll(".edge").forEach((e) =>
        e.classList.toggle("dim", sel && e.dataset.src !== id
          && e.dataset.dst !== id));
    }));
  document.querySelectorAll("[data-act]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api(`/exceptions/${id}/action`,
          {method: "POST", headers: {"Content-Type": "application/json",
           "X-Role": ROLE}, body: JSON.stringify({action: b.dataset.act})});
      } catch (e) { alert(e.reason || e.error); }
      kpis(); reconTable(); detail(id); stream();
    }));

}

/* ---------- root causes & prevention (real /clusters) ---------- */
async function clusters() {
  const { clusters } = await api("/clusters");
  $("#clusters").innerHTML = clusters.map((c) => `
    <div class="card cluster ${c.status === "FALSE_PATTERN" ? "false" : ""}">
      <h3>${c.cluster_title} \u00b7 <span class="chip
        ${c.status === "CONFIRMED" ? "ok" : "REJECTED"}">${c.status}</span>
        \u00b7 trend ${c.trend}</h3>
      <div class="big">${rupee(c.gross_leakage_paise)}</div>
      <p class="mono">${c.affected_transaction_count} exceptions \u00b7
        recovered ${rupee(c.recovered_paise)}
        ${c.ai_claimed_count_corrected ?
          " \u00b7 AI count corrected from source" : ""}</p>
      <p class="mono">${c.validation_reason}</p>
      ${c.prevention ? `<div class="prev"><b>${c.prevention.label}:
        ${rupee(c.prevention.estimated_preventable_paise)}</b>
        (priority ${c.prevention.priority}) \u2014
        ${c.prevention.proposed_control}</div>` : ""}
    </div>`).join("");
}

/* ---------- evaluation (real /evaluation, animated bars) ---------- */
async function evaluation() {
  const { result } = await api("/evaluation");
  const rows = [
    ["A \u00b7 Matcher only",
     `recall ${(result.variant_a.leak_recall * 100).toFixed(0)}% \u00b7
      precision ${(result.variant_a.leak_precision * 100).toFixed(0)}%`,
     result.cases],
    ["B \u00b7 + AI + containment",
     `${result.variant_b.correct} correct \u00b7 escaped
      <span class="red">${result.variant_b.escaped}</span>`,
     result.variant_b.correct],
    ["C \u00b7 + gates + decision",
     `${result.variant_c.packages} filed \u00b7
      ${result.variant_c.write_off} written off`,
     result.variant_c.packages],
    ["D \u00b7 full Trace",
     `net ${rupee(result.variant_d.waterfall.net_recovered_paise)}
      (ACTUAL) \u00b7 preventable
      ${rupee(result.variant_d.estimated_preventable_paise)} (ESTIMATED)`,
     result.variant_c.packages]];
  const w = result.variant_d.waterfall;
  const WF = [["Gross leakage (OBSERVED)", w.gross_leakage_paise, ""],
    ["Claimed (after 8 gates)", w.claimed_paise, ""],
    ["Approved by counterparties", w.approved_paise, ""],
    ["Recovered (ACTUAL)", w.recovered_paise, ""],
    ["Net recovered", w.net_recovered_paise, ""],
    ["Preventable (ESTIMATED)",
     result.variant_d.estimated_preventable_paise, "est"]];
  const wmax = Math.max(...WF.map((x) => x[1]));
  const wfHtml = `<div class="wf-money">${WF.map(([n, v, cls]) =>
    `<div class="row"><span>${n}</span>
     <span class="bar ${cls}"><i data-w="${(v / wmax * 100).toFixed(1)}">
     </i></span><span>${rupee(v)}</span></div>`).join("")}</div>`;
  const max = Math.max(...rows.map((r) => r[2]));
  $("#evaluation").innerHTML = wfHtml + `<div class="abl">
    ${rows.map(([name, note, val]) => `<div class="row">
      <span>${name}</span>
      <span class="bar"><i data-w="${(val / max * 100).toFixed(0)}"></i>
      </span><span>${note}</span></div>`).join("")}</div>
    <p class="mono">integrity ${result.integrity.status} \u00b7 run
      ${result.evaluation_run_id} \u00b7 reproducibility hash
      ${result.evaluation_result_hash.slice(0, 16)}\u2026</p>`;
  const bars = document.querySelectorAll("#evaluation .bar i");
  observe([$("#evaluation")], "on");
  $("#evaluation").addEventListener("revealed", () =>
    bars.forEach((i) => i.style.width = i.dataset.w + "%"));
  if (REDUCED) bars.forEach((i) => i.style.width = i.dataset.w + "%");
}

async function stream() {
  const { events } = await api("/stream?n=30");
  $("#stream").innerHTML = events.slice().reverse().map((e) =>
    `<li>#${e.seq} \u00b7 ${e.event_type} \u00b7 ${e.case_id}</li>`)
    .join("");
}

$("#verify").addEventListener("click", async () => {
  const v = await api("/audit/verify");
  const msg = v.valid
    ? `\u2713 ${v.events} events verified \u00b7 no mutation detected`
    : `\u2717 first invalid at #${v.first_invalid_seq}`;
  $("#chainstate").textContent = msg;
  $("#auditsum").textContent = msg;
});

story(); kpis(); reconTable(); clusters(); evaluation(); stream();
setInterval(stream, 5000);
