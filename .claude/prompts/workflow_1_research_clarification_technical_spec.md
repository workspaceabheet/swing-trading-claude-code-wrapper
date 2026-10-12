# Workflow 1: Research, Clarification, and Technical Specification

## Overview

This workflow turns an initial idea into a well-aligned, high-level technical specification through structured intake, staged research, solution clarification, and requirements definition.

The workflow has four main stages:

1. Lightweight intake
2. Research
3. Solution clarification and alignment
4. Technical specification

## Stage 1: Lightweight Intake

**Goal:** Understand the user's initial idea and clarify the problem before conducting research.

- Ask targeted questions to understand the idea, goals, constraints, and context.
- Identify ambiguities and missing information.
- Clarify the problem as thoroughly as possible before moving forward.
- Keep the interaction conversational and focused.

**Output:** A concise understanding of the problem, goals, and initial scope.

## Stage 2: Research

Research consists of three sub-stages.

### 2.1 Generate Research Questions

Use a single grounding agent to turn the initial understanding into structured research questions across relevant domains, such as:

- Product idea and user needs
- Architecture and system design
- Technical feasibility and constraints
- Business model, market, and competition
- Security, privacy, operations, and other relevant areas

Present the proposed question sets to the user and ask whether there are additional topics or questions they want researched before beginning the parallel research phase.

**Output:** A user-reviewed set of research questions grouped by domain.

### 2.2 Run Parallel Research Agents

- Spawn multiple lightweight, low-cost model agents.
- Assign each agent a distinct set of research questions or domain.
- Run the agents in parallel to improve speed.
- Keep each agent's scope focused and avoid unnecessary duplication.
- Capture findings, evidence, sources, assumptions, and unresolved questions where applicable.

**Output:** Separate research results for each question set or domain.

### 2.3 Synthesize the Research

- Use a capable but cost-conscious model for synthesis—for example, Sonnet.
- Consolidate the individual research results into a coherent report.
- Highlight key findings, trade-offs, risks, options, assumptions, and open questions.
- Distinguish supported findings from uncertain conclusions.
- Avoid using an unnecessarily expensive model when a less costly model is sufficient.

**Output:** A consolidated research report presented to the user.

### Research Artifacts and Storage

- Store all artifacts in a session-specific directory under `.sessions/` in the relevant repository.
- Keep outputs from individual research agents separate from the final synthesized report.
- Use the intended Dropbox folder as the storage location for the workflow and its artifacts, subject to the repository's configured storage setup.

## Stage 3: Solution Clarification and Alignment

**Goal:** Use the research findings to decide what should actually be built.

After presenting the research report:

- Ask the user targeted follow-up questions about the desired solution.
- Clarify scope, priorities, expected behavior, constraints, and trade-offs.
- Offer recommendations based on the research rather than leaving every decision open-ended.
- For each question, explain:
  - Why the question matters
  - What decision it is intended to clarify
  - The direction or answer currently recommended
  - The implications of the available choices, where useful
- Continue until there is sufficient alignment to define the solution.

**Output:** An agreed solution direction, scope, priorities, and set of requirements.

## Stage 4: Create the Technical Specification

**Goal:** Produce a high-level specification that clearly describes what needs to be built and how success will be evaluated.

The specification should include, as relevant:

- Problem statement and goals
- Target users and use cases
- Scope and out-of-scope items
- Functional requirements
- High-level architecture or solution direction
- Important constraints, dependencies, and assumptions
- Expected outputs and deliverables
- Acceptance criteria for each major feature or requirement
- Test expectations and acceptance criteria for validation
- Risks, open questions, and unresolved decisions

Keep the document at the **requirements and high-level design level**. It should explain what the system needs to do and what constitutes success, without prescribing code-level implementation details prematurely.

**Output:** A clear, testable, high-level technical specification aligned with the user's needs.

## Cross-Cutting Principles

- **User alignment:** Involve the user at important decision points and avoid silently assuming requirements.
- **Cost efficiency:** Use lightweight models for focused research and stronger models for synthesis when justified.
- **Parallelism:** Research independent question sets concurrently.
- **Traceability:** Preserve research findings and session artifacts so decisions can be traced back to evidence.
- **Clarity:** Explain why questions are being asked and provide recommendations, not just lists of options.
- **Testability:** Ensure requirements have clear, measurable acceptance criteria.
- **Session isolation:** Keep artifacts organized by session in `.sessions/`.
- **Scope discipline:** Keep the final specification focused on requirements and high-level design rather than code-level implementation.

## Workflow Summary

```text
Initial idea
    |
    v
Stage 1: Lightweight intake and problem clarification
    |
    v
Stage 2.1: Generate domain-specific research questions
    |
    v
User reviews/adds research topics
    |
    v
Stage 2.2: Parallel low-cost research agents
    |
    v
Stage 2.3: Synthesize findings with a capable, cost-conscious model
    |
    v
Present research report
    |
    v
Stage 3: Clarify and align on the desired solution
    |
    v
Stage 4: Produce a high-level technical specification
    |
    v
Save session artifacts under .sessions/<session-id>/
```
