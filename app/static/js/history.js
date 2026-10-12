/**
 * History view: browse past runs and view their details.
 * Manages two views: list (all past runs) and detail (one run's full idea list).
 */
(function () {
  const listView = document.getElementById("history-list-view");
  const detailView = document.getElementById("history-detail-view");
  const historyRows = document.getElementById("history-rows");
  const backBtn = document.getElementById("back-to-list");
  const detailMeta = document.getElementById("history-detail-meta");
  const detailIdeas = document.getElementById("history-detail-ideas");
  const detailDisclaimer = document.getElementById("history-disclaimer");
  const runRowTemplate = document.getElementById("run-row-template");

  let currentRun = null;

  function showListView() {
    listView.hidden = false;
    detailView.hidden = true;
    currentRun = null;
  }

  function showDetailView() {
    listView.hidden = true;
    detailView.hidden = false;
  }

  function buildRunRow(run) {
    const node = runRowTemplate.content.cloneNode(true);
    const row = node.querySelector(".history-row");

    // Status styling
    if (run.status === "error") {
      row.classList.add("history-row--error");
    } else if (run.quick_sweep_skipped) {
      row.classList.add("history-row--skipped");
    }

    node.querySelector(".history-row-id").textContent = `Run #${run.run_id}`;
    node.querySelector(".history-row-status").textContent = run.status;
    node.querySelector(".history-row-started").textContent = run.started_at;

    if (run.finished_at) {
      node.querySelector(".history-row-finished").textContent = `finished ${run.finished_at}`;
    } else {
      node.querySelector(".history-row-finished").textContent = "";
    }

    node.querySelector(".history-row-cost").textContent = `$${run.total_cost_usd.toFixed(2)}`;

    if (run.quick_sweep_skipped) {
      node.querySelector(".history-row-skip").hidden = false;
    }

    row.addEventListener("click", () => loadDetail(run.run_id));
    return node;
  }

  async function loadList() {
    try {
      const response = await apiFetch("/api/runs?limit=50&offset=0");
      historyRows.innerHTML = "";

      if (!response.runs || response.runs.length === 0) {
        historyRows.innerHTML = '<p class="empty-state">No runs yet.</p>';
        return;
      }

      for (const run of response.runs) {
        historyRows.appendChild(buildRunRow(run));
      }
    } catch (err) {
      historyRows.innerHTML = '<p class="error-state">Failed to load run history.</p>';
    }
  }

  async function loadDetail(runId) {
    try {
      const run = await apiFetch(`/api/run/${runId}`);

      if (!run.has_run) {
        showListView();
        return;
      }

      currentRun = run;
      renderDetail();
      showDetailView();
    } catch (err) {
      if (err.status === 404) {
        alert("Run not found.");
        showListView();
      } else {
        alert("Failed to load run details.");
      }
    }
  }

  function formatCostBreakdown(run) {
    // Format: "Cost: $0.0152 (sweep $0.0010 · deep-dive $0.0042 · compilation $0.0100)"
    const total = (run.total_cost_usd || 0).toFixed(4);
    const sweep = (run.cost_sweep_usd || 0).toFixed(4);
    const deepDive = (run.cost_deep_dive_usd || 0).toFixed(4);
    const compilation = (run.cost_compilation_usd || 0).toFixed(4);
    return `$${total} (sweep $${sweep} · deep-dive $${deepDive} · compilation $${compilation})`;
  }

  function renderDetail() {
    if (!currentRun) return;

    // Render metadata
    detailMeta.innerHTML = `
      <div class="run-detail-header">
        <h2>Run #${currentRun.run_id}</h2>
        <span class="run-detail-status">${currentRun.status}</span>
      </div>
      <div class="run-detail-meta">
        <p><strong>Started:</strong> ${currentRun.started_at}</p>
        <p><strong>Finished:</strong> ${currentRun.finished_at || "—"}</p>
        <p><strong>Cost:</strong> ${formatCostBreakdown(currentRun)}</p>
        ${currentRun.quick_sweep_skipped ? '<p><strong>⊘ Quick-sweep skipped</strong></p>' : ''}
      </div>
    `;

    // Render ideas
    detailIdeas.innerHTML = "";
    if (!currentRun.ideas || currentRun.ideas.length === 0) {
      detailIdeas.innerHTML = '<p class="empty-state">No ideas for this run.</p>';
    } else {
      // Partition ideas into regular and low-confidence
      const regularIdeas = currentRun.ideas.filter(idea => !idea.low_confidence);
      const lowConfidenceIdeas = currentRun.ideas.filter(idea => idea.low_confidence);

      // Render regular ideas section
      if (regularIdeas.length > 0) {
        const heading = document.createElement("h3");
        heading.textContent = "Ideas";
        detailIdeas.appendChild(heading);

        const container = document.createElement("div");
        container.className = "ideas-container";
        for (const idea of regularIdeas) {
          container.appendChild(buildIdeaCard(idea));
        }
        detailIdeas.appendChild(container);
      }

      // Render low-confidence ideas section if any exist
      if (lowConfidenceIdeas.length > 0) {
        const heading = document.createElement("h3");
        heading.textContent = "Lower-confidence ideas (backfilled)";
        heading.className = "low-confidence-section-heading";
        detailIdeas.appendChild(heading);

        const container = document.createElement("div");
        container.className = "low-confidence-ideas-container";
        for (const idea of lowConfidenceIdeas) {
          container.appendChild(buildIdeaCard(idea));
        }
        detailIdeas.appendChild(container);
      }
    }

    // Render disclaimer
    detailDisclaimer.textContent = currentRun.disclaimer || "";
    detailDisclaimer.hidden = !currentRun.disclaimer;
  }

  backBtn.addEventListener("click", showListView);

  // Initial load
  loadList();
})();
