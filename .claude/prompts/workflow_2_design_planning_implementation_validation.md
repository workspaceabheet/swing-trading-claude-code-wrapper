# Workflow 2: Design, Planning, Implementation, and End-to-End Validation

## Overview

This workflow takes the technical specification produced by Workflow 1 and turns it into a working, independently validated product.

Its core principles are:

- Plan collaboratively with the user.
- Organize implementation into small, testable **vertical slices**.
- Implement one slice at a time using a single coder agent.
- Make each completed slice available for user testing.
- Validate the complete product independently against the original technical specification.

## Inputs

- The approved technical specification from Workflow 1
- Relevant research findings and session context
- Repository and project configuration
- User-approved scope and priorities

## Stage 1: Initial Planning and User Alignment

**Goal:** Propose an initial plan and agree with the user on what will be built.

1. Read the technical specification and relevant research context.
2. Draft an initial implementation plan.
3. Identify the major capabilities, user journeys, APIs, interfaces, data needs, and integration points.
4. Explain the proposed plan to the user in understandable terms.
5. Ask focused questions about important choices and uncertainties.
6. Recommend a default direction for each meaningful decision and explain why.
7. Incorporate the user's modifications and confirm alignment before proceeding.

**Output:** A user-approved initial plan and clarified scope.

## Stage 2: Canonical Structural Plan Using Vertical Slices

**Goal:** Break the plan into small, independently testable increments that deliver end-to-end functionality.

### Vertical-slicing principles

- Do not plan separate horizontal phases such as “build the entire frontend” followed by “build the entire backend.”
- Each slice should deliver a coherent piece of user-visible or otherwise verifiable functionality.
- Where applicable, a slice should connect the UI, API, backend logic, and persistence required for that capability.
- Keep slices small enough to implement, test, demonstrate, and review independently.
- Order slices according to dependencies and prioritize an early working path through the system.
- Avoid slices that are merely layers or infrastructure with no clear validation outcome, unless foundational work is genuinely necessary.

### Define every slice

For each slice, specify:

- Name and intended outcome
- User value or capability delivered
- Scope and explicit exclusions
- Frontend, backend, API, and data responsibilities as applicable
- Dependencies and prerequisites
- Acceptance criteria
- Automated and manual tests
- How to run or access the slice
- What the user should be able to verify
- Completion and validation conditions

Each slice must result in a testable workflow. For example, a web application slice might expose a working page and API endpoint that the user can run and exercise.

**Output:** A canonical, ordered structural plan of vertical slices with clear acceptance criteria.

## Stage 3: Detailed Technical Planning

**Goal:** Expand the canonical plan into an implementation-ready execution plan.

For each slice, document:

- Specific files to create, modify, or remove
- Responsibilities of each relevant module
- Interfaces, API contracts, and data models
- Frontend/backend integration details
- Data flow and error handling
- Dependencies on earlier slices
- Step-by-step implementation sequence
- Test files and test cases
- Commands or procedures to run the tests
- Instructions for launching and demonstrating the slice
- Acceptance criteria and verification evidence expected

The plan should be detailed enough for a coder agent to execute without having to invent major design decisions. Resolve important ambiguities with the user before implementation.

Keep the plan aligned with the technical specification. If a material scope or architectural change becomes necessary, bring it to the orchestrator and user rather than silently changing the agreed solution.

**Output:** A complete, detailed technical implementation plan organized by vertical slice.

## Stage 4: Incremental Implementation

**Goal:** Implement the plan slice by slice, with local verification and continuous user feedback.

Use **one independent coder agent** for implementation. The orchestrator manages the overall workflow and does not replace the coder by directly doing the implementation itself.

### Per-slice execution loop

For each planned slice:

1. Select the next slice whose dependencies are satisfied.
2. Give the coder agent the relevant slice plan, project context, constraints, and acceptance criteria.
3. Have the coder implement the slice.
4. Have the coder run relevant tests, inspect the result, and fix issues found during its own verification.
5. Launch the application or relevant local server so the functionality can be exercised.
6. Present the completed slice to the user, including how to run or access it and what to test.
7. Invite feedback and clarify whether the user wants changes.
8. Route requested changes through the coder and re-verify the affected functionality.
9. Mark the slice complete only when its required checks pass and the user has had the opportunity to review it.
10. Continue to the next slice.

Keep the server available for user testing when practical and safe. Clearly communicate prerequisites, local URLs, test accounts or setup steps, and any limitations. Do not claim a server is running unless that has been verified.

After all slices are implemented, run a quick implementation-level regression check before the independent validation stage.

**Output:** A working application assembled from verified, user-reviewable vertical slices.

## Stage 5: Independent End-to-End Validation

**Goal:** Verify the complete application against the original technical specification without relying solely on the coder agent's claims or self-tests.

The validation process must be independent of the coder's implementation and verification process. It may use a separate validator agent or an independently executed validation workflow.

### Validation procedure

1. Re-read the original technical specification and all acceptance criteria.
2. Set up and launch the application using documented instructions.
3. Exercise complete user journeys across relevant frontend, backend, API, and persistence boundaries.
4. Run the required automated tests and appropriate manual checks.
5. Verify each acceptance criterion against observable behavior.
6. Check important failure cases, boundary conditions, and integration behavior.
7. Record results, evidence, failures, and missing functionality.
8. Produce a requirement-by-requirement acceptance report.

### Failure and repair loop

- If a criterion fails or functionality is missing, report the specific failure to the orchestrator.
- The orchestrator assigns the repair to the coder agent, including reproduction steps and the expected behavior.
- The coder fixes the issue and runs relevant tests.
- Re-run the independent validation for the affected criteria and any potentially impacted regression areas.
- Repeat until all acceptance criteria pass or a blocker prevents completion.

Never report full acceptance when criteria remain unverified or failing. If something cannot be validated, label it clearly as blocked, untested, or unresolved and explain why.

**Output:** An independent end-to-end validation report mapping every acceptance criterion to a pass, fail, or blocked status.

## Artifacts and Session Management

Store workflow artifacts in the session-specific directory under `.sessions/<session-id>/` in the repository. Use the intended Dropbox folder for storage where the project environment supports it.

Suggested artifacts:

- `initial-plan.md`
- `vertical-slice-plan.md`
- `detailed-implementation-plan.md`
- `slice-status.md`
- `validation-report.md`
- Relevant test output, evidence, and session notes

Keep plans and reports updated as approved decisions or implementation results change. Do not overwrite the original technical specification without explicit authorization.

## Cross-Cutting Principles

- **User alignment:** Ask the user to resolve consequential product decisions and provide recommendations rather than presenting unexplained choices.
- **Vertical slices:** Prefer small, end-to-end, independently testable capabilities over horizontal layer-by-layer implementation.
- **Incremental feedback:** Give the user a working result to review after each slice.
- **Single coder:** Use one coder agent for the implementation sequence to maintain continuity and reduce conflicting edits.
- **Testability:** Every slice must have explicit acceptance criteria and a practical verification path.
- **Independent validation:** Final acceptance must be based on observed end-to-end behavior, not the coder's self-report alone.
- **Traceability:** Map requirements to slices, tests, and final validation outcomes.
- **Honest status:** Never claim tests passed, a server is running, or a requirement is satisfied without evidence.
- **Controlled changes:** Route material changes to scope or architecture through the orchestrator and user.
- **Recovery:** Failures return to the orchestrator, which coordinates repair and re-validation.

## Workflow Summary

```text
Technical specification + relevant research
    |
    v
Stage 1: Initial plan and user alignment
    |
    v
Stage 2: Canonical plan of vertical slices
    |
    v
Stage 3: Detailed technical plan
    |
    v
Stage 4: Single coder implements one slice at a time
    |
    +--> Self-test and verify
    +--> Launch for user testing
    +--> Collect feedback and revise
    |
    v
Quick implementation-level regression check
    |
    v
Stage 5: Independent end-to-end validation
    |
    +--> All criteria pass --> Final acceptance report
    |
    +--> Failure/blocker --> Orchestrator --> Coder repair
                                      |
                                      v
                               Re-validation
```
