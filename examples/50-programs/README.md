# AlgoLang: 50 Sample Programs

The runnable source of every program in **[AlgoLang: 50 Sample Programs](../../docs/AlgoLang_50_Sample_Programs.pdf)** (PDF, 106 pages) by Dr. S. Satyanarayana, AlgoProfessor AI R&D Solutions.

For every program, the PDF shows the input, the AlgoLang code and the output in all three modes: command line, the graphical Studio and the Prompt UI. It also sets out the objectives and design principles of the language and a summary of its syntax.

**50 programs · 21 sectors · patterns:** pipeline 15 · router 13 · fan-out 9 · par for 5 · single 4 · committee 4

## Run one

```bash
cd examples/50-programs
algo run P14_credit_committee.algo --arg "application=Salaried, income 85000 per month, existing EMI 12000, requests 15 lakh home loan"
algo studio                       # open any of them in the graphical Studio
```

The exact inputs used in the PDF are in [`inputs.json`](inputs.json). CI compiles and runs all 50 on every push (`tests/test_50_programs.py`).

## The programs

| # | Program | Sector | Pattern | What it shows |
|---|---|---|---|---|
| 1 | [Hello Greeter](P01_hello_greeter.algo) | Basics | single | The smallest AlgoLang program: one agent called by one flow. |
| 2 | [Article Summariser](P02_article_summariser.algo) | Basics | single | One agent that condenses text. |
| 3 | [Sentiment Scorer](P03_sentiment_scorer.algo) | Basics | single | An agent whose return type is score, a value between 0 and 1. |
| 4 | [Translator](P04_translator.algo) | Basics | single | An agent with two inputs. |
| 5 | [Study Planner](P05_study_planner.algo) | Basics | pipeline | Each agent’s output feeds the next one. |
| 6 | [Blog Post Pipeline](P06_blog_post_pipeline.algo) | Basics | pipeline | Four agents in sequence: outline, draft, edit, headline. |
| 7 | [Pros and Cons Judge](P07_pros_and_cons_judge.algo) | Basics | fan-out | Two analysts run in parallel; a judge weighs both. |
| 8 | [Idea Ranker](P08_idea_ranker.algo) | Basics | par for | par for evaluates every idea in parallel. |
| 9 | [ER Triage Router](P09_er_triage_router.algo) | Healthcare | router | Decision support: high urgency goes to a clinician at once; a human confirms. |
| 10 | [Discharge Summary](P10_discharge_summary.algo) | Healthcare | pipeline | Notes become a clinician summary and then a patient-friendly copy. |
| 11 | [Care Team Review](P11_care_team_review.algo) | Healthcare | fan-out | Three specialties review in parallel; a coordinator merges. |
| 12 | [Drug Interaction Check](P12_drug_interaction_check.algo) | Pharma | fan-out | Three checks run together; the brief goes to a pharmacist. |
| 13 | [Adverse Event Router](P13_adverse_event_router.algo) | Pharma | router | Serious events get an expedited report; others are logged. |
| 14 | [Credit Committee](P14_credit_committee.algo) | Banking | committee | Three scorers vote; the chair recommends. Protected attributes are forbidden. |
| 15 | [KYC Onboarding](P15_kyc_onboarding.algo) | Banking | pipeline | Identity, sanctions screening, then an onboarding recommendation. |
| 16 | [Fraud Alert Router](P16_fraud_alert_router.algo) | Banking | router | High fraud scores hold the payment for human review. |
| 17 | [Claims Triage](P17_claims_triage.algo) | Insurance | router | Risky claims go to investigators; the rest are fast-tracked. |
| 18 | [Renewal Advisor](P18_renewal_advisor.algo) | Insurance | pipeline | Risk review, pricing, then a customer letter. |
| 19 | [Earnings Brief](P19_earnings_brief.algo) | Capital | fan-out | Bull, bear and risk views are written in parallel and merged. |
| 20 | [Trade Compliance Check](P20_trade_compliance_check.algo) | Capital | router | Risky trades are escalated to a human. |
| 21 | [Quiz Generator](P21_quiz_generator.algo) | Education | pipeline | Questions, then distractors, then an answer key. |
| 22 | [Admissions Panel](P22_admissions_panel.algo) | Education | committee | Merit-only panel; gender, caste and religion are forbidden. |
| 23 | [CO-PO Mapper](P23_co_po_mapper.algo) | Education | par for | One mapper per outcome, then a matrix. |
| 24 | [Literature Review](P24_literature_review.algo) | Research | par for | Papers are read in parallel with a search tool, then synthesised. |
| 25 | [Hypothesis Critic](P25_hypothesis_critic.algo) | Research | fan-out | Three critics in parallel, one editor. |
| 26 | [Grievance Router](P26_grievance_router.algo) | Government | router | Urgent grievances get a priority desk and service-level target. |
| 27 | [Welfare Pre-check](P27_welfare_pre_check.algo) | Government | pipeline | Rules, documents, and a citizen letter. Religion and caste are forbidden inputs. |
| 28 | [NDA Triage](P28_nda_triage.algo) | Legal | router | Low-risk NDAs are approved; risky ones go to a lawyer. |
| 29 | [Clause Reviewer](P29_clause_reviewer.algo) | Legal | par for | Each clause is checked in parallel, then summarised. |
| 30 | [Fair CV Screening](P30_fair_cv_screening.algo) | HR | committee | Three scorers and a chair; protected attributes are forbidden. |
| 31 | [Interview Builder](P31_interview_builder.algo) | HR | pipeline | Competencies, questions, then a scoring rubric. |
| 32 | [Exit Interview Insights](P32_exit_interview_insights.algo) | HR | fan-out | Themes, tone and actions run in parallel. |
| 33 | [Defect Root Cause](P33_defect_root_cause.algo) | Manufacturing | pipeline | Symptoms, ranked causes, corrective actions. |
| 34 | [Maintenance Planner](P34_maintenance_planner.algo) | Manufacturing | router | High failure risk produces an urgent work order. |
| 35 | [Shipment Exception](P35_shipment_exception.algo) | Supply | pipeline | Diagnose, find recovery options, tell the customer. |
| 36 | [Supplier Risk Panel](P36_supplier_risk_panel.algo) | Supply | committee | Three risk scores and a procurement decision. |
| 37 | [Product Copy Studio](P37_product_copy_studio.algo) | Retail | fan-out | Three channels write in parallel; a brand checker merges. |
| 38 | [Complaint Reply](P38_complaint_reply.algo) | Retail | router | Very upset customers get a manager-level apology. |
| 39 | [Incident Triage](P39_incident_triage.algo) | IT | pipeline | Classify, assess impact, choose the runbook. |
| 40 | [Postmortem Writer](P40_postmortem_writer.algo) | IT | pipeline | Timeline, root cause, and a blameless report. |
| 41 | [SOC Alert Enrichment](P41_soc_alert_enrichment.algo) | Cybersecurity | pipeline | An enrichment agent with a declared search tool, then severity and a plan. |
| 42 | [Phishing Email Check](P42_phishing_email_check.algo) | Cybersecurity | router | Suspicious mail is quarantined; the rest is delivered with a note. |
| 43 | [Grid Anomaly Router](P43_grid_anomaly_router.algo) | Energy | router | Abnormal readings alert a human operator. |
| 44 | [Solar Site Assessment](P44_solar_site_assessment.algo) | Energy | fan-out | Sun, grid and cost views are merged into a brief. |
| 45 | [Crop Advisory](P45_crop_advisory.algo) | Agriculture | pipeline | Soil reading, action steps, and a simple advisory. |
| 46 | [Pest Alert Triage](P46_pest_alert_triage.algo) | Agriculture | router | Likely outbreaks alert the district officer. |
| 47 | [Claim Fact-Check](P47_claim_fact_check.algo) | Media | par for | Each claim is checked with a search tool, then reported. |
| 48 | [Headline Variants](P48_headline_variants.algo) | Media | fan-out | Three styles in parallel; an editor picks. |
| 49 | [Listing Writer](P49_listing_writer.algo) | Real | pipeline | Features, copy, and a fair-housing language check. |
| 50 | [Hotel Review Responder](P50_hotel_review_responder.algo) | Hospitality | router | Happy guests get thanks; unhappy ones get a service-recovery reply. |

## The six patterns

| Pattern | How it works |
|---|---|
| single | One agent, one flow |
| pipeline | Each agent's output feeds the next agent |
| fan-out | `par { … }` runs several agents together; one agent merges the results |
| committee | Several scoring agents run in parallel; a chair agent decides. Protected attributes can be forbidden by policy |
| router | A score decides which agent handles the case (`if score >= t`) |
| par for | `par for x in list` fans one agent out over a list; another summarises |

The PDF's outputs were produced with AlgoLang 0.2.0's offline backend. All 50 programs run unchanged on 0.3.0, which adds cost, energy and CO₂ estimates to each run summary.
