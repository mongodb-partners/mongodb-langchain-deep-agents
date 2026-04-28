# Healthcare pack

Clinical-operations assistant for hospital staff. Not patient-facing.

## Personas

- Case manager coordinating a discharge
- Pharmacy reviewing an antibiotic order
- Infection-control analyst investigating a CDI cluster
- Quality analyst auditing sepsis bundle compliance

## Operational schema

| Collection | Shape |
|---|---|
| `patients` | `{ _id, initials, dob_yr, sex, allergies[], problem_list[] }` |
| `encounters` | `{ _id, patient_id, admit_ts, discharge_ts, unit, primary_dx }` |
| `medications` | `{ _id, patient_id, drug, dose, route, frequency, start_ts, stop_ts }` |

## Knowledge-base themes

- IDSA C. difficile treatment (vancomycin / fidaxomicin)
- Surviving Sepsis Campaign 1-hour bundle
- CDC antibiotic stewardship core elements
- PHI redaction rules (HIPAA Safe Harbor identifiers)
- Discharge-planning requirements for Medicare/Medicaid

## Hard rules

- Never advise individual patients directly.
- Always mask PHI to initials + last-4 (or similar partial) in output.
- Cite guidelines by name and version.
- If evidence is ambiguous, flag the ambiguity.

## Demo flow

```mermaid
flowchart TD
    U["Clinical staff<br/>Case manager / pharmacy / IC analyst<br/>'What is first-line for non-severe CDI?'<br/>'Is the sepsis bundle complete on enc_H9003?'<br/>'Any active abx on pt_H001?'"]
    U --> P["Main planner<br/>(clinically-grounded voice,<br/>PHI-masking rules baked in)"]
    P -->|'CDI treatment', 'sepsis bundle'| KB[("knowledge_base<br/>IDSA, SSC, CDC stewardship")]
    P -->|'drug interaction'| KG[("knowledge_graph<br/>drug<->diagnosis<->infection-control")]
    P -->|chart review| DA["Data agent<br/>allow_list: {patients,<br/>encounters, medications}"]
    DA --> OC[("patients / encounters / medications<br/>PHI stored as initials + dob_yr")]
    P -->|deep dive| R["Researcher subagent"]
    R --> KB
    R --> W["web_search<br/>(CDC / IDSA / AHRQ)"]
    W --> FC["fetch_and_cache"]
    FC --> KB
    P --> GUARD{"PHI mask?<br/>Guideline cite?"}
    GUARD -->|yes| ANS["Clinician-facing briefing<br/>+ guideline citations<br/>+ PHI masked"]
    GUARD -->|ambiguous| FLAG["Flag ambiguity,<br/>recommend escalation"]

    classDef mongo fill:#00684a,color:#fff,stroke:#004c3a
    classDef safety fill:#fff4e5,stroke:#c2410c
    class KB,KG,OC mongo
    class GUARD,FLAG safety
```

Demo vignettes:
- **Stewardship review**: "pt_H001 is on vancomycin 125 mg PO QID for CDI -
  is that first-line per the current IDSA guideline?" -> KB hit on
  `guideline/idsa-cdi-2021`, chart confirmation via data agent, cited
  answer with masked initials.
- **Sepsis bundle audit**: "Did enc_H9003 receive lactate + cultures +
  abx + fluids within the 1-hour bundle?" -> multi-collection join
  (`encounters`, `medications`), KB citation on `guideline/ssc-2021-bundle`.
- **Discharge readiness**: "Is the 24-hour discharge-plan-eval window
  met on the CDI admit?" -> KB on `policy/cms-discharge-planning-482.43`.
