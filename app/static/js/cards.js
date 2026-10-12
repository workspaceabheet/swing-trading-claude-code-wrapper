/**
 * Shared idea-card rendering function used by both the latest-run view (run.js)
 * and the history detail view (history.js). Encapsulates the card template cloning
 * and field population logic.
 */

function buildIdeaCard(idea) {
  const ideaTemplate = document.getElementById("idea-card-template");
  const node = ideaTemplate.content.cloneNode(true);
  const article = node.querySelector(".idea-card");

  node.querySelector(".idea-ticker").textContent = idea.ticker;

  const tierEl = node.querySelector(".idea-tier");
  tierEl.textContent = idea.tier;
  tierEl.classList.add(`tier-${idea.tier}`);

  node.querySelector(".idea-entry").textContent = idea.entry;
  node.querySelector(".idea-target").textContent = idea.target;
  node.querySelector(".idea-hold").textContent = `${idea.hold_days}d`;
  node.querySelector(".idea-rationale").textContent = idea.rationale;

  const citationEl = node.querySelector(".idea-citation");
  citationEl.href = idea.citation_url;

  if (idea.low_confidence) {
    node.querySelector(".idea-low-confidence-label").hidden = false;
    article.classList.add("idea-card--low-confidence");
  }

  return node;
}
