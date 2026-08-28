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

/* ---------- boot hero: the system coming online ---------- */
const LIFECYCLE = ["OBSERVE","RECONCILE","DETECT","INVESTIGATE","PROVE","DECIDE","RECOVER","VERIFY","LEARN","PREVENT"];
async function hero() {
  const h = await api("/health");
  const el = document.createElement("section");
  el.id = "hero";
  el.innerHTML = `
   <div class="boot wordmark">TRACE<span>.</span></div>
   <div class="boot sys">SYSTEM ONLINE \u00b7 <b>${h.exceptions}</b>
     EXCEPTIONS UNDER INVESTIGATION \u00b7 CLOCK
     <span id="liveclock"></span> \u00b7
     ${h.mode.toUpperCase()}</div>
   <div class="boot tag">Find the money that disappeared between payment
     and settlement.</div>
   <div class="boot doctrine">AI INVESTIGATES<i></i>SYSTEMS PROVE<i></i>
     POLICY DECIDES<i></i>THE EXECUTOR ACTS</div>
   <div class="boot down">\u2193</div>`;
  document.querySelector("main").prepend(el);
  const tick = () => {
    const n = new Date();
    const d = n.toLocaleDateString("en-GB",
      { day: "2-digit", month: "short", year: "numeric" }).toUpperCase();
    const tm = n.toLocaleTimeString("en-US",
      { hour: "2-digit", minute: "2-digit", second: "2-digit",
        hour12: true });
    const c = $("#liveclock");
    if (c) c.textContent = `${d} \u00b7 ${tm}`;
  };
  tick();
  setInterval(tick, 1000);   // hero stays in the DOM through dossier
                             // open/close, scroll and filters — the
                             // interval keeps ticking throughout
  const boots = [...el.querySelectorAll(".boot")];
  boots.forEach((b, i) => setTimeout(() => b.classList.add("on"),
    REDUCED ? 0 : 200 + i * 300));
  const sweep = document.createElement("div");
  sweep.className = "sweep";
  document.body.appendChild(sweep);
  if (!REDUCED) {                       // floating particles, fixed seeds
    const dust = document.createElement("div");
    dust.className = "dustfield";
    dust.innerHTML = Array.from({length: 14}, (_, i) =>
      `<span class="dust" style="left:${(i * 7.3 + 3) % 100}%;
       animation-delay:-${(i * 1.7) % 16}s"></span>`).join("");
    document.body.appendChild(dust);
  }
  if (!REDUCED) {
    let ticking = false;
    addEventListener("scroll", () => {
      if (!ticking) requestAnimationFrame(() => {
        document.body.style.setProperty("--scroll", scrollY);
        ticking = false;
      }), ticking = true;
    }, { passive: true });
  }
}

/* ---------- the Overview story: ten beats, real numbers ---------- */
async function story() {
  const [k, ev, ex] = await Promise.all([
    api("/kpis"), api("/evaluation"), api("/exceptions")]);
  const r = ev.result;
  const sample = ex.exceptions.find((e) =>
    e.type === "missing_settlement") || ex.exceptions[0];
  const BEATS = [
    {kick: "OBSERVE", intro: "Money appears correct.",
     looks: "Orders \u00b7 Payments \u00b7 Refunds \u00b7 Settlements",
     happens: "Trace starts by gathering the financial trail \u2014 " +
       "5,000 orders across a simulated quarter \u2014 and builds the " +
       "financial picture before deciding anything is wrong.",
     why: "A recovery system should start with evidence, not a guess."},
    {kick: "RECONCILE", intro: "Then it asks a simple question: should " +
       "these records agree?",
     looks: "Order book \u00b7 Gateway ledger \u00b7 Bank statements",
     happens: "Deterministic rules tie every capture to its fee, " +
       "settlement and bank posting \u2014 to the paisa.",
     why: `They don't always agree: <b class="num">
       ${rupee(k.leakage_found_paise)}</b> of leakage hides in this
       quarter.`},
    {kick: "DETECT", intro: "When they don't, Trace points to the " +
       "exact break.",
     looks: "The evidence graph \u2014 every record, every relationship",
     happens: `A leak is a broken edge: ${sample.order.id} settled at
       the gateway, and the bank never posted the UTR \u2014
       <b class="num">${rupee(Math.abs(sample.delta_paise))}</b>
       short.`,
     why: "Naming the exact broken relationship is what makes a claim " +
       "provable later."},
    {kick: "INVESTIGATE", intro: "AI can investigate what might have " +
       "happened \u2014 but its answer is still only a hypothesis.",
     looks: "Read-only tools: orders, transactions, batches, UTRs, " +
       "refunds, fee schedules",
     happens: "A bounded investigator reads only what the tools return " +
       "and proposes a cause, labeled UNVERIFIED.",
     why: "The AI never touches money and never defines truth."},
    {kick: "PROVE", intro: "Deterministic checks decide whether the " +
       "numbers actually support the claim.",
     looks: "Recomputed amounts \u00b7 contract rules \u00b7 " +
       "record hashes",
     happens: `The AI was wrong <b class="num">${r.variant_b.errors}</b>
       times on the held-out benchmark.`,
     why: `Errors that escaped containment:
       <b class="num">${r.variant_b.escaped}</b>. That number is the
       product.`},
    {kick: "DECIDE", intro: "Not every leak is worth chasing.",
     looks: "Eight admissibility gates \u00b7 counterparty economics " +
       "\u00b7 deadlines",
     happens: `<b class="num">${r.variant_c.packages}</b> claims filed
       \u00b7 <b class="num">${r.variant_c.write_off}</b> written off
       because pursuit costs more than return \u00b7
       <b class="num">${r.variant_c.escalate}</b> sent to humans.`,
     why: "Money owed is not the same as money worth pursuing."},
    {kick: "RECOVER", intro: "Only cases that pass the required gates " +
       "can reach the executor.",
     looks: "Immutable action packages \u00b7 idempotency keys \u00b7 " +
       "package hashes",
     happens: "One execution per exception \u2014 ever \u2014 across " +
       "retries, timeouts and duplicates.",
     why: `Double executions so far:
       <b class="num">${k.double_executions}</b>.`},
    {kick: "VERIFY", intro: "After an action, Trace checks what " +
       "actually happened.",
     looks: "Counterparty responses \u00b7 the recovery ledger \u00b7 " +
       "the audit chain",
     happens: `Actual recovery, verified against the ledger:
       <b class="num">${rupee(k.recovered_paise)}</b> gross,
       <b class="num">${rupee(k.net_recovered_paise)}</b> net.`,
     why: "Recovered means reconciled to the paisa, not claimed."},
    {kick: "LEARN", intro: "Repeated leaks reveal patterns.",
     looks: "Clusters by leak type and counterparty",
     happens: "Patterns are proposed by AI and confirmed only when they " +
       "survive deterministic challenge \u2014 false patterns are " +
       "rejected, not shipped.",
     why: "One systemic cause explains dozens of individual leaks."},
    {kick: "PREVENT", intro: "The goal is not just to recover " +
       "yesterday's money. It is to stop tomorrow's leak.",
     looks: "Confirmed root causes \u00b7 recurrence rates \u00b7 " +
       "mitigation costs",
     happens: `Fixing the causes is worth an <span class="est">estimated
       <b class="num">${rupee(k.estimated_preventable_paise)}</b></span>
       in future leakage.`,
     why: "Labeled ESTIMATED \u2014 never added to actual recovery."}];
  $("#story").innerHTML = BEATS.map((b, i) => `
    <div class="beat"><div class="card-story">
      <span class="chapter">${String(i + 1).padStart(2, "0")}</span>
      <span class="kick">${b.kick}</span>
      <p>${wordize(b.intro)}</p>
      <div class="facts">
        <div><span class="flab">WHAT TRACE LOOKS AT</span>
          <span class="fval">${b.looks}</span></div>
        <div><span class="flab">WHAT HAPPENS</span>
          <span class="fval">${b.happens}</span></div>
        <div><span class="flab">WHY IT MATTERS</span>
          <span class="fval">${b.why}</span></div>
      </div>
      <div class="rulebar"></div>
    </div></div>`).join("");
  $("#rail").innerHTML = LIFECYCLE.map((s, i) =>
    `<button class="stage" data-beat="${i}"
      aria-label="Go to ${s}">${s}</button>`).join("");
  // ROOT-CAUSE FIX: the chapters are position:sticky, so a chapter the
  // user has scrolled PAST is pinned at rect.top ~ 0 — scrollIntoView
  // then computes a destination equal to the current position and
  // upward navigation goes nowhere. Navigate to the chapter's STATIC
  // layout slot instead: the story's document offset plus the summed
  // flow heights of all previous chapters (offsetHeight is layout
  // truth, immune to sticky pinning). Works identically in both
  // directions from any scroll position.
  function scrollToLifecycle(i) {
    const story = $("#story");
    const beats = [...story.querySelectorAll(".beat")];
    if (!beats[i]) return;
    const headerOffset =
      document.querySelector(".topbar").offsetHeight || 0;
    let top = story.getBoundingClientRect().top + scrollY;
    for (let j = 0; j < i; j++) top += beats[j].offsetHeight;
    window.scrollTo({ top: Math.max(0, top - headerOffset),
                      behavior: REDUCED ? "auto" : "smooth" });
    // clicked item becomes active immediately; the existing
    // IntersectionObserver (class toggles only — it never scrolls, so
    // it cannot cancel this navigation) takes back over as the user
    // moves on.
    document.querySelectorAll("#rail .stage").forEach((d, j) => {
      d.classList.toggle("on", j === i);
      d.classList.toggle("done", j < i);
    });
  }
  document.querySelectorAll("#rail .stage").forEach((st) =>
    st.addEventListener("click", () =>
      scrollToLifecycle(+st.dataset.beat)));
  const dots = [...document.querySelectorAll("#rail .stage")];
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
          dots.forEach((d, j) => {
            d.classList.toggle("on", j === idx);
            d.classList.toggle("done", j < idx);
          });
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
  if (!document.querySelector(".contain")) {
    const b = (await api("/evaluation")).result.variant_b;
    const strip = document.createElement("div");
    strip.className = "contain";
    strip.innerHTML = `<span>AI INVESTIGATION<b>${b.errors}</b> errors
      </span><span>CONTAINED<b>${b.contained}</b></span>
      <span class="escaped">ESCAPED<b>${b.escaped}</b></span>
      <span style="opacity:.7">AI can be wrong \u2014 the architecture
      keeps wrong AI output from becoming financial truth</span>`;
    $("#cards").before(strip);
  }
  const types = [...new Set(ALL_CASES.map((e) => e.type))].sort();
  const decisions = [...new Set(ALL_CASES.map((e) => e.decision))].sort();
  $("#filters").innerHTML = ["all", ...types, ...decisions].map((tp) =>
    `<button data-f="${tp}" class="${tp === FILTER ? "on" : ""}">
     ${tp.replace(/_/g, " ")}</button>`).join("");
  document.querySelectorAll("#filters button").forEach((b) =>
    b.addEventListener("click", () => { FILTER = b.dataset.f;
      reconTable(); }));
  $("#search").oninput = (ev) => { QUERY = ev.target.value.toLowerCase();
    drawCards(); };
  drawCards();
}
function drawCards() {
  const rows = ALL_CASES.filter((e) =>
    (FILTER === "all" || e.type === FILTER || e.decision === FILTER)
    && (!QUERY || `${e.order.id} ${e.exception_id} ${e.gateway.id}
        ${e.type} ${e.decision} ${e.state}`
        .toLowerCase().includes(QUERY)));
  $("#count").textContent = `${rows.length} of ${ALL_CASES.length}
    cases`;
  $("#cards").innerHTML = rows.map((e) => `
    <div class="case" tabindex="0" data-id="${e.exception_id}">
      <div class="head"><span class="oid">${e.order.id}</span>
        <span class="delta">\u2212${rupee(Math.abs(e.delta_paise))}</span>
      </div>
      <div class="ledger3">
        <div><b>ORDER</b>${e.order.id}</div>
        <div><b>${e.gateway.gw}</b>${rupee(e.gateway.amount_paise)}</div>
        <div class="short"><b>BANK</b>${rupee(e.bank.expected_paise)}
          \u2192 ${rupee(e.bank.actual_paise)}</div>
      </div>
      <div class="foot"><span class="chip type"><span class="dot">
        </span>${e.type}</span>
        <span class="chip warn">${e.decision.replace(/_/g, " ")}</span>
        <span class="chip ${e.evidence}">${e.evidence}</span></div>
      <div class="meta">${e.exception_id} \u00b7 ${e.gateway.id}
        \u00b7 state ${e.state} \u00b7 deadline
        ${e.deadline.slice(0, 10)}</div>
    </div>`).join("") || `<p class='mono' style='grid-column:1/-1;padding:22px;
    text-align:center'>No cases match the current filter and search.
    Clear them to see all ${ALL_CASES.length} cases.</p>`;
  const cardEls = [...document.querySelectorAll(".case")];
  cardEls.forEach((c, i) => {
    c.style.transitionDelay = REDUCED ? "0s" : `${(i % 6) * 70}ms`;
    c.setAttribute("role", "button");
    c.setAttribute("aria-label", "Open case " + c.dataset.id);
    c.addEventListener("click", (ev) => detail(c.dataset.id, ev));
    c.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") detail(c.dataset.id, ev);
    });
  });
  if (REDUCED) cardEls.forEach((c) => c.classList.add("on"));
  else observe(cardEls, "on");
}

/* ---------- detail: interactive graph, animated gates, timeline ------- */
async function detail(id, ev) {
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
  if (ev) {
    ov.style.setProperty("--ox", ev.clientX + "px");
    ov.style.setProperty("--oy", ev.clientY + "px");
  }
  ov.innerHTML = `<div class="file">
   <div class="rail2">${STEPS.map((s) =>
     `<div class="step ${hit.has(s) ? "hit" : ""}">${s}</div>`).join("")}
   </div><div class="body">
   <button class="close" id="closeov">CLOSE \u2715</button>
   <h2>${id}</h2>
   <div class="seq">${["CASE IDENTIFIED", "RECORDS LOADED", "RECONCILING",
     "EVIDENCE FOUND", "DISCREPANCY CONFIRMED"]
     .map((s) => `<span>${s}</span>`).join("<i></i>")}</div>
   <div class="dossier">
     <div><div class="lab">CASE</div>
       <div class="val">${id.replace("exc_", "").toUpperCase()
         .slice(0, 18)}</div></div>
     <div><div class="lab">ORDER ID</div>
       <div class="val">${d.discrepancy.order_id}</div></div>
     <div><div class="lab">GATEWAY / TRANSACTION</div>
       <div class="val">${Object.values(d.evidence_graph.nodes)
         .find((n) => n.table === "gateway_txns")?.id || "\u2014"}
       </div></div>
     <div><div class="lab">STATUS</div>
       <div class="val">${d.case.state}</div></div>
     <div><div class="lab">TYPE</div>
       <div class="val">${d.discrepancy.discrepancy_type
         .replace(/_/g, " ").toUpperCase()}</div></div>
     <div><div class="lab">OBSERVED LOSS</div>
       <div class="val loss">${rupee(Math.abs(
         d.discrepancy.delta_paise))}</div></div>
     <div><div class="lab">DECISION</div>
       <div class="val">${d.decision.selected_action}</div></div>
     <div><div class="lab">EVIDENCE</div>
       <div class="val">${d.ai.verdict === "SUPPORTED"
         ? "VERIFIED" : d.ai.verdict}</div></div>
   </div>
   <p class="sub">deadline ${d.discrepancy.claim_deadline}</p>
   <div class="finrec">
     <div><div class="lab">EXPECTED</div>
       <div class="val">${rupee(d.discrepancy.expected_paise)}</div></div>
     <div><div class="lab">ACTUAL</div>
       <div class="val">${rupee(d.discrepancy.actual_paise)}</div></div>
     <div><div class="lab">DELTA</div>
       <div class="val neg">\u2212${rupee(Math.abs(
         d.discrepancy.delta_paise))}</div></div>
   </div>
   ${moneyFlow(d)}
   ${brokenEdge(d)}
   <div class="stagewrap"><div class="cols">
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
      <p class="mono">verdict: <b>${d.ai.verdict}</b></p>
      <div class="ladder">
        <div class="rung ai"><span>AI INVESTIGATOR</span>
          <span>"hypothesis"</span></div>
        <div class="arrow">\u2193</div>
        <div class="rung det"><span>DETERMINISTIC EVIDENCE</span>
          <span>"verified"</span></div>
        <div class="arrow">\u2193</div>
        <div class="rung det"><span>POLICY ENGINE</span>
          <span>"decision"</span></div>
        <div class="arrow">\u2193</div>
        <div class="rung det"><span>BOUNDED EXECUTOR</span>
          <span>"action"</span></div>
      </div></div>
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
   </div></div></div>`;
  const closeFile = () => {
    ov.classList.add("closing");
    setTimeout(() => { ov.hidden = true; ov.classList.remove("closing");
      document.body.style.overflow = ""; document.onkeydown = null;
    }, REDUCED ? 0 : 200);            // overlay is fixed: scroll intact
  };
  $("#closeov").addEventListener("click", closeFile);
  ov.addEventListener("click", (e) => { if (e.target === ov) closeFile(); });
  document.onkeydown = (e) => { if (e.key === "Escape") closeFile(); };
  $("#closeov").focus();
  const seq = [...ov.querySelectorAll(".seq span")];
  seq.forEach((s, i) => setTimeout(() => s.classList.add("lit"),
    REDUCED ? 0 : 160 + i * 210));
  setTimeout(() => {
    ov.querySelector(".stagewrap").classList.add("go");
    ov.querySelector(".gates").classList.add("gates-on");
    ov.querySelector(".tl").classList.add("go");
    ov.querySelectorAll(".tl li").forEach((li, i) =>
      li.style.transitionDelay = REDUCED ? "0s" : `${i * 110}ms`);
  }, REDUCED ? 0 : 420);
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
  const b = result.variant_b, c = result.variant_c;
  const wd = result.variant_d.waterfall;
  const wall = `<div class="bench">
    <div class="lead">AI was allowed to fail \u2014 and the system
      remained safe.</div>
    <div class="trio">
      <div><div class="v" data-n="${b.errors}">0</div>
        <div class="k">AI ERRORS</div></div>
      <div><div class="v" data-n="${b.contained}">0</div>
        <div class="k">CONTAINED</div></div>
      <div class="escaped"><div class="v" data-n="${b.escaped}">
        ${b.escaped}</div><div class="k">ESCAPED</div></div>
    </div>
    <div class="stats">
      <span><b data-n="${result.cases}">0</b>hidden leak cases</span>
      <span><b>${(result.variant_a.leak_recall * 100).toFixed(0)}% /
        ${(result.variant_a.leak_precision * 100).toFixed(0)}%</b>
        recall / precision</span>
      <span><b data-n="${c.packages}">0</b>claims filed</span>
      <span><b data-n="${c.write_off}">0</b>written off</span>
      <span><b data-n="${c.escalate}">0</b>escalated</span>
      <span><b>${rupee(wd.recovered_paise)}</b>recovered gross
        (ACTUAL)</span>
      <span><b>${rupee(wd.net_recovered_paise)}</b>recovered net
        (ACTUAL)</span>
      <span><b>${rupee(result.variant_d.estimated_preventable_paise)}</b>
        prevented (ESTIMATED)</span>
    </div>
    <div class="note">held-out benchmark \u00b7 integrity
      ${result.integrity.status} \u00b7 all figures live from the
      evaluation artifact</div>
  </div>
  <p class="ae-note">Estimated prevention is intentionally never merged
    with actual recovered money \u2014 a core Trace design
    principle.</p>`;
  const wfHtml = wall + `<div class="wf-money">${WF.map(([n, v, cls]) =>
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
  const counters = document.querySelectorAll("#evaluation [data-n]");
  $("#evaluation").addEventListener("revealed", () => {
    bars.forEach((i) => i.style.width = i.dataset.w + "%");
    counters.forEach((el) => countUp(el, +el.dataset.n,
      (x) => x.toLocaleString("en-IN")));
  });
  if (REDUCED) {
    bars.forEach((i) => i.style.width = i.dataset.w + "%");
    counters.forEach((el) =>
      el.textContent = (+el.dataset.n).toLocaleString("en-IN"));
  }
  footer();
}

function moneyFlow(d) {
  const leakStage = {missing_settlement: 3, fee_overcharge: 1,
    double_refund: 1, duplicate_capture: 1, rounding_drift: 2,
    partial_capture_mismatch: 2,
    refund_marked_success_not_settled: 3}[
    d.discrepancy.discrepancy_type] ?? 2;
  const stages = [
    ["CUSTOMER PAYMENT", d.evidence_graph.nodes &&
      Object.values(d.evidence_graph.nodes).find((n) =>
        n.table === "orders")?.amount_paise],
    ["GATEWAY", Object.values(d.evidence_graph.nodes).find((n) =>
        n.table === "gateway_txns")?.amount_paise],
    ["EXPECTED SETTLEMENT", d.discrepancy.expected_paise],
    ["ACTUAL BANK SETTLEMENT", d.discrepancy.actual_paise]];
  return `<div class="flow">${stages.map(([n, v], i) => `
    <div class="stage ${i === leakStage + 1 || (i === 3 &&
      leakStage >= 2) ? "leak" : ""}"><span>${n}</span>
      <span>${v != null ? rupee(v) : "\u2014"}</span></div>
    ${i < 3 ? `<div class="pipe ${i >= leakStage ? "broken" : ""}">
      </div>` : ""}`).join("")}
    <div class="pipe ${leakStage < 4 ? "broken" : ""}"></div>
    <div class="stage leak"><span>DISCREPANCY</span>
      <span>\u2212${rupee(Math.abs(d.discrepancy.delta_paise))}
      \u2192 ${d.decision.selected_action.replace(/_/g, " ")}</span>
    </div></div>`;
}
function brokenEdge(d) {
  const broken = d.evidence_graph.edges.some((e) => e.broken);
  const nodes = ["ORDER", "GATEWAY", "SETTLEMENT", "BANK"];
  return `<div class="edgeline">${nodes.map((n, i) => `
    <span class="n">${n}</span>
    ${i < 3 ? (i === 2 && broken ?
      `<span class="e x"></span><span class="xmark">\u2715
       POSTED_AS</span><span class="e x"></span>`
      : `<span class="e"></span>`) : ""}`).join("")}
    ${broken ? `<span class="chip EXCEPTION">EXCEPTION CREATED</span>`
      : ""}</div>`;
}

function footer() {
  if (document.querySelector("footer")) return;
  const f = document.createElement("footer");
  f.innerHTML = `<div class="fw">TRACE</div>
    <div class="fd">AI INVESTIGATES. SYSTEMS PROVE. POLICY DECIDES.
      EXECUTOR ACTS.</div>
    <div class="flags"><span>SIMULATED WORLD</span>
      <span>STUDENT PROJECT</span>
      <span>ARCHITECTURE DEMONSTRATION</span>
      <span>NOT A PRODUCTION FINANCIAL PRODUCT</span></div>`;
  document.querySelector("main").appendChild(f);
}

let LAST_SEQ = -1;
async function stream() {
  const { events } = await api("/stream?n=30");
  $("#stream").innerHTML = events.slice().reverse().map((e) =>
    `<li class="${e.seq > LAST_SEQ && LAST_SEQ >= 0 ? "new" : ""}">
     #${e.seq} \u00b7 ${e.event_type} \u00b7 ${e.case_id}</li>`)
    .join("");
  LAST_SEQ = Math.max(LAST_SEQ, ...events.map((e) => e.seq));
}

const sys = document.createElement("span");
sys.id = "sysstate"; sys.textContent = "SYSTEM READY";
document.querySelector(".top-right").prepend(sys);
$("#verify").addEventListener("click", async () => {
  sys.className = "busy";
  sys.textContent = "VERIFYING\u2026";
  const vp = api("/audit/verify");            // the REAL endpoint
  if (!REDUCED) await new Promise((r) => setTimeout(r, 300));
  sys.textContent = "CHECKING AUDIT EVENTS\u2026";
  if (!REDUCED) await new Promise((r) => setTimeout(r, 300));
  sys.textContent = "VERIFYING HASH CHAIN\u2026";
  const v = await vp;
  const msg = v.valid
    ? `\u2713 ${v.events} events verified \u00b7 no mutation detected`
    : `\u2717 first invalid at #${v.first_invalid_seq}`;
  sys.className = v.valid ? "" : "busy";
  sys.textContent = v.valid ? "AUDIT VERIFIED" : "AUDIT INVALID";
  $("#chainstate").textContent = msg;
  $("#auditsum").textContent = msg;
});

(() => {  // initial navigation state: ALWAYS Overview at the top.
  // Root causes fixed here, not cosmetically:
  // (1) the tabs are hash anchors, so a refresh after clicking one
  //     jumps straight back to that section via the URL hash;
  // (2) browsers restore the previous scroll position on refresh
  //     (scrollRestoration defaults to "auto");
  // (3) at scroll 0 the hero (not a tab target) fills the viewport,
  //     so without an explicit default no tab is active at all.
  if ("scrollRestoration" in history)
    history.scrollRestoration = "manual";            // fixes (2)
  if (location.hash)
    history.replaceState(null, "", location.pathname); // fixes (1)
  scrollTo(0, 0);
  const first = document.querySelector(".tabs a");
  if (first) first.classList.add("active");          // fixes (3)
})();
function initTabTracking() {
  // Attached ONLY after the initial renders complete (see bootstrap
  // below). ROOT CAUSE of the flaky initial underline: these observers
  // used to attach synchronously at parse time, when every section was
  // still EMPTY — zero-height #rootcauses / #evalsec sat inside the
  // first viewport's detection band, fired isIntersecting immediately,
  // and overwrote the Overview default; WHICH one won depended on the
  // async hero prepend shifting layout mid-paint, giving the
  // nondeterministic Root Causes / Evaluation starts. With real
  // geometry in place, only the section actually in the band (the
  // story, at scroll 0) can assert itself.
  const tabs = [...document.querySelectorAll(".tabs a")];
  tabs.forEach((a, i) => {
    const s = document.querySelector(a.hash);
    if (!s) return;
    new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) tabs.forEach((x) =>
        x.classList.toggle("active", x === tabs[i]));
    }), { rootMargin: "-30% 0px -60% 0px" }).observe(s);
  });
}
(async () => {   // bootstrap: render first, observe second — no timers
  await Promise.all([hero(), story(), kpis(), reconTable(), clusters(),
                     evaluation(), stream()]);
  initTabTracking();
})();
setInterval(stream, 5000);
