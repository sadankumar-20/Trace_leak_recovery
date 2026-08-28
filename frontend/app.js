const $ = (s) => document.querySelector(s);
const rupee = (p) => "Rs." + (p / 100).toLocaleString("en-IN",
  {maximumFractionDigits: 0});
const api = (u, o) => fetch(u, o).then(async (r) => {
  const j = await r.json();
  if (!r.ok) throw j;
  return j;
});
const ROLE = "executor";   // demo role; the API enforces it server-side

async function kpis() {
  const k = await api("/kpis");
  $("#kpis").innerHTML = `
   ${tile(k.leakage_found_paise, "leakage found", "OBSERVED")}
   ${tile(k.claimed_paise, "claimed", "VERIFIED")}
   ${tile(k.recovered_paise, "recovered", k.labels.recovered)}
   ${tile(k.net_recovered_paise, "net recovered", "ACTUAL")}
   ${tile(k.written_off_paise, "written off", "STOPPING RULE")}
   ${tile(k.estimated_preventable_paise, "prevented future loss",
          k.labels.preventable, true)}`;
}
const tile = (v, k, tag, est) => `<div class="kpi ${est ? "est" : ""}">
  <div class="v">${rupee(v)}</div><div class="k">${k}</div>
  <div class="tag">${tag}</div></div>`;

async function reconTable() {
  const { exceptions } = await api("/exceptions");
  $("#recon tbody").innerHTML = exceptions.map((e) => `
    <tr class="row" data-id="${e.exception_id}">
      <td>${e.order.id}</td>
      <td>${e.gateway.gw} ${e.gateway.id}<br>${rupee(e.gateway.amount_paise)}</td>
      <td>${rupee(e.bank.expected_paise)} \u2192 ${rupee(e.bank.actual_paise)}</td>
      <td class="delta">${rupee(e.delta_paise)}</td>
      <td><span class="chip EXCEPTION">${e.type}</span></td>
      <td><span class="chip warn">${e.decision}</span></td>
      <td><span class="chip ok">${e.state}</span></td></tr>`).join("");
  document.querySelectorAll("tr.row").forEach((tr) =>
    tr.addEventListener("click", () => detail(tr.dataset.id)));
}

async function detail(id) {
  const d = await api("/exceptions/" + id);
  const g = d.evidence_graph;
  const gates = d.admissibility ? Object.entries(
    d.admissibility.gate_results).map(([k, v]) =>
    `<div class="gate"><span>${k}</span><span class="g-${v}">${v}</span>
     </div>`).join("") : "<em>no gate run (verdict not supported)</em>";
  $("#detail").hidden = false;
  $("#detail").innerHTML = `
   <h2>${id} \u00b7 ${d.discrepancy.discrepancy_type} \u00b7
       \u0394 ${rupee(Math.abs(d.discrepancy.delta_paise))} \u00b7
       deadline ${d.discrepancy.claim_deadline}</h2>
   <div class="cols">
    <div class="card"><h3>EVIDENCE GRAPH (${Object.keys(g.nodes).length}
      hash-verified nodes)</h3>
      ${Object.values(g.nodes).map((n) => `<div class="node">${n.table}
        \u00b7 ${n.id}<br>${n.amount_paise != null ?
        rupee(n.amount_paise) : ""} <span class="lineage">
        ${n.record_hash.slice(0, 10)}\u2026</span></div>`).join("")}
      ${g.edges.map((e) => `<div class="edge ${e.broken ? "broken" : ""}">
        ${e.src} \u2500${e.type}\u2192 ${e.dst || "\u2718 MISSING"}
        </div>`).join("")}</div>
    <div class="card"><h3>AI INVESTIGATION</h3>
      <div class="unverified">${d.ai.hypothesis.label}:
        <b>${d.ai.hypothesis.type}</b>
        (${rupee(d.ai.hypothesis.amount_paise)})</div>
      <p class="mono">tools: ${d.ai.tools_used.join(" \u2192 ")}</p>
      <p class="mono">verdict: <b>${d.ai.verdict}</b></p></div>
    <div class="card"><h3>ADMISSIBILITY \u2014 8 GATES</h3>${gates}</div>
    <div class="card"><h3>DECISION</h3>
      <p><b>${d.decision.selected_action}</b></p>
      <p class="mono">${d.decision.reason}</p>
      ${Object.entries(d.decision.rejected_actions || {}).map(([a, r]) =>
        `<p class="mono">\u2717 ${a}: ${r}</p>`).join("")}</div>
    <div class="card"><h3>EXECUTION &amp; RECOVERY</h3>
      ${d.execution ? `<p class="mono">${d.execution.execution_id} \u00b7
        <span class="chip ${d.execution.execution_status}">
        ${d.execution.execution_status}</span> \u00b7 attempts
        ${d.execution.attempt_count}</p>` : "<p>none</p>"}
      ${d.recovery ? `<p class="mono">recovered
        ${rupee(d.recovery.recovered_paise)} \u00b7 net
        ${rupee(d.recovery.net_recovery_paise)} \u00b7 ref
        ${d.recovery.counterparty_reference}</p>` : ""}</div>
    <div class="card"><h3>CASE &amp; AUDIT (${d.audit.length} events)</h3>
      <p class="mono">state: ${d.case.state}</p>
      ${d.audit.slice(-6).map((e) => `<div class="mono">#${e.seq}
        ${e.event_type}</div>`).join("")}</div>
   </div>
   <div class="actions">${Object.entries(d.allowed_actions).map(([a, i]) =>
     `<button class="btn" data-act="${a}" ${i.enabled ? "" : "disabled"}
       title="${i.reason.replace(/"/g, "'")}">${a}</button>`).join("")}
   </div>
   <p class="mono">disabled actions show the machine reason on hover \u2014
     enforcement is server-side, the UI only reflects it</p>`;
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

async function stream() {
  const { events } = await api("/stream?n=30");
  $("#stream").innerHTML = events.slice().reverse().map((e) =>
    `<li>#${e.seq} \u00b7 ${e.event_type} \u00b7 ${e.case_id}</li>`)
    .join("");
}

$("#verify").addEventListener("click", async () => {
  const v = await api("/audit/verify");
  $("#chainstate").textContent = v.valid
    ? `\u2713 ${v.events} events verified \u00b7 no mutation detected`
    : `\u2717 first invalid at #${v.first_invalid_seq}`;
});

kpis(); reconTable(); stream(); setInterval(stream, 5000);
