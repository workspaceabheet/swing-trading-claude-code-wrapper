(function () {
  const POLL_INTERVAL_MS = 2000;

  const runBtn = document.getElementById("run-btn");
  const statusArea = document.getElementById("status-area");
  const noticeArea = document.getElementById("notice-area");
  const costArea = document.getElementById("cost-area");
  const ideasArea = document.getElementById("ideas-area");
  const disclaimerEl = document.getElementById("disclaimer");
  const ideaTemplate = document.getElementById("idea-card-template");
  const sourcesSection = document.getElementById("sources-section");
  const sourcesGroups = document.getElementById("sources-groups");
  const failedSourcesNotice = document.getElementById("failed-sources-notice");
  const sourceGroupTemplate = document.getElementById("source-group-template");
  const sourceItemTemplate = document.getElementById("source-item-template");

  let pollTimer = null;

  function setNotice(message) {
    noticeArea.textContent = message || "";
  }

  function setStatusText(message) {
    statusArea.textContent = message || "";
  }

  function setCostText(message) {
    costArea.textContent = message || "";
  }

  function setButtonBusy(busy) {
    runBtn.disabled = busy;
  }

  function renderEmptyState() {
    ideasArea.innerHTML = '<p class="empty-state">No runs yet. Click "Run now" to generate ideas.</p>';
    disclaimerEl.hidden = true;
    sourcesSection.hidden = true;
    setCostText("");
  }

  function renderIdeas(ideas, disclaimer) {
    ideasArea.innerHTML = "";
    if (!ideas || ideas.length === 0) {
      ideasArea.innerHTML = '<p class="empty-state">No ideas found for the last run.</p>';
    } else {
      // Partition ideas into regular and low-confidence
      const regularIdeas = ideas.filter(idea => !idea.low_confidence);
      const lowConfidenceIdeas = ideas.filter(idea => idea.low_confidence);

      // Render regular ideas section
      if (regularIdeas.length > 0) {
        const heading = document.createElement("h2");
        heading.textContent = "Ideas";
        ideasArea.appendChild(heading);

        const container = document.createElement("div");
        container.className = "ideas-container";
        for (const idea of regularIdeas) {
          container.appendChild(buildIdeaCard(idea));
        }
        ideasArea.appendChild(container);
      }

      // Render low-confidence ideas section if any exist
      if (lowConfidenceIdeas.length > 0) {
        const heading = document.createElement("h2");
        heading.textContent = "Lower-confidence ideas (backfilled)";
        heading.className = "low-confidence-section-heading";
        ideasArea.appendChild(heading);

        const container = document.createElement("div");
        container.className = "low-confidence-ideas-container";
        for (const idea of lowConfidenceIdeas) {
          container.appendChild(buildIdeaCard(idea));
        }
        ideasArea.appendChild(container);
      }
    }
    disclaimerEl.textContent = disclaimer || "";
    disclaimerEl.hidden = !disclaimer;
  }

  const SOURCE_LABELS = {
    moneycontrol_rss: "Moneycontrol",
    nse_bhavcopy: "NSE Bhavcopy (EOD)",
    screener_in: "Screener.in",
    trading_economics: "Trading Economics",
  };

  function renderFailedSources(failedSources) {
    if (!failedSources || failedSources.length === 0) {
      failedSourcesNotice.hidden = true;
      failedSourcesNotice.textContent = "";
      return;
    }
    failedSourcesNotice.hidden = false;
    failedSourcesNotice.textContent = `Sources unavailable this run: ${failedSources.join(", ")}`;
  }

  function renderSources(sources, failedSources) {
    sourcesGroups.innerHTML = "";
    renderFailedSources(failedSources);

    if (!sources || sources.length === 0) {
      if (!failedSources || failedSources.length === 0) {
        sourcesSection.hidden = true;
        return;
      }
      sourcesSection.hidden = false;
      return;
    }
    sourcesSection.hidden = false;

    const bySource = new Map();
    for (const source of sources) {
      if (!bySource.has(source.source)) {
        bySource.set(source.source, []);
      }
      bySource.get(source.source).push(source);
    }

    for (const [sourceName, items] of bySource) {
      sourcesGroups.appendChild(buildSourceGroup(sourceName, items));
    }
  }

  function buildSourceGroup(sourceName, items) {
    const node = sourceGroupTemplate.content.cloneNode(true);
    node.querySelector(".source-group-label").textContent =
      SOURCE_LABELS[sourceName] || sourceName;
    const list = node.querySelector(".sources-list");
    for (const item of items) {
      list.appendChild(buildSourceItem(item));
    }
    return node;
  }

  function buildSourceItem(source) {
    const node = sourceItemTemplate.content.cloneNode(true);
    const headlineEl = node.querySelector(".source-headline");
    headlineEl.textContent = source.headline;
    headlineEl.href = source.url;
    node.querySelector(".source-published").textContent = source.published_at;
    node.querySelector(".source-snippet").textContent = buildSourceDetail(source);
    return node;
  }

  function buildSourceDetail(source) {
    if (source.close != null) {
      return `Close ${source.close} (prev ${source.prev_close}), volume ${source.volume}`;
    }
    if (source.pe_ratio != null || source.market_cap_cr != null) {
      return `P/E ${source.pe_ratio ?? "n/a"}, market cap Rs ${source.market_cap_cr ?? "n/a"} cr`;
    }
    if (source.indicator_value != null) {
      return `${source.indicator_name}: ${source.indicator_value}`;
    }
    return source.snippet;
  }

  function formatCostLine(run) {
    // Format: "Cost: $0.0042 (sweep $0.0003, deep-dive $0.0035, compilation $0.0004)"
    const total = (run.total_cost_usd || 0).toFixed(4);
    const sweep = (run.cost_sweep_usd || 0).toFixed(4);
    const deepDive = (run.cost_deep_dive_usd || 0).toFixed(4);
    const compilation = (run.cost_compilation_usd || 0).toFixed(4);
    return `Cost: $${total} (sweep $${sweep}, deep-dive $${deepDive}, compilation $${compilation})`;
  }

  function renderRunState(lastRun) {
    if (!lastRun.has_run) {
      renderEmptyState();
      return;
    }
    if (lastRun.status === "running") {
      setStatusText("Run in progress...");
      setCostText("");
      return;
    }
    if (lastRun.status === "error") {
      ideasArea.innerHTML = '<p class="empty-state">The last run failed. Try again.</p>';
      disclaimerEl.hidden = true;
      sourcesSection.hidden = true;
      setStatusText("");
      setCostText(formatCostLine(lastRun));
      return;
    }
    renderIdeas(lastRun.ideas, lastRun.disclaimer);
    renderSources(lastRun.sources, lastRun.failed_sources);
    setStatusText("");
    setCostText(formatCostLine(lastRun));
  }

  async function hydrateLastRun() {
    try {
      const [status, lastRun] = await Promise.all([
        apiFetch("/api/run/status"),
        apiFetch("/api/run/last"),
      ]);
      if (status.in_progress) {
        setStatusText("Run in progress...");
        setButtonBusy(true);
        startPolling();
      } else {
        renderRunState(lastRun);
      }
    } catch (err) {
      setNotice("Could not load the last run.");
    }
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function pollStatus() {
    try {
      const status = await apiFetch("/api/run/status");
      if (!status.in_progress) {
        stopPolling();
        setStatusText("");
        setButtonBusy(false);
        const lastRun = await apiFetch("/api/run/last");
        renderRunState(lastRun);
      }
    } catch (err) {
      stopPolling();
      setButtonBusy(false);
      setNotice("Lost connection while polling run status.");
    }
  }

  async function handleRunClick() {
    setButtonBusy(true);
    setNotice("");
    setStatusText("Starting run...");
    try {
      await apiFetch("/api/run", { method: "POST" });
      setStatusText("Run in progress...");
      startPolling();
    } catch (err) {
      if (err.status === 409) {
        setNotice("A run is already in progress.");
        setStatusText("Run in progress...");
        startPolling();
      } else {
        setButtonBusy(false);
        setStatusText("");
        setNotice("Failed to start run.");
      }
    }
  }

  runBtn.addEventListener("click", handleRunClick);

  hydrateLastRun();
})();
