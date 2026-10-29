#!/usr/bin/env python3
"""
make_packs.py — builds the AlgoLang domain-pack library (packs/) from the table below.

    python tools/make_packs.py            # writes packs/<sector>/<pack>.algo and packs/catalog.json

Each line of DOMAINS is one domain:
    id | title | input | risk | people | shape | tools | slots | description

  risk    high / medium / low  → human-review threshold 0.90 / 0.80 / 0.70 and token budget
  people  y if the pack makes or supports decisions about people → protected attributes forbidden
  shape   pipe | fan | committee | router   (see SHAPES below)
  tools   comma list from kb, calc, file, web (granted to the first agent)
  slots   Name=goal;Name=goal;…  goals may use {in} {prev} {item} {items} {score}

Add your organisation's own domains to DOMAINS (or a second file) and re-run: every pack is
compiled before it is written, so the library can never contain a broken program.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from algoc import compile_source  # noqa: E402

SECTORS = {
    "healthcare": "Healthcare", "pharma": "Pharma & Life Sciences", "banking": "Banking",
    "insurance": "Insurance", "markets": "Capital Markets & Investment", "education": "Education",
    "research": "Research & Academia", "government": "Government & Public Services",
    "legal": "Legal & Compliance", "hr": "HR & Workforce", "manufacturing": "Manufacturing",
    "supplychain": "Supply Chain & Logistics", "retail": "Retail & E-commerce",
    "itops": "Telecom & IT Operations", "cyber": "Cybersecurity", "energy": "Energy & Utilities",
    "agriculture": "Agriculture", "media": "Media & Marketing",
    "realestate": "Real Estate & Construction", "hospitality": "Hospitality & Travel",
}

DOMAINS = """
# ── healthcare ──
healthcare.clinical_triage|Clinical note triage|note|high|y|pipe|kb|Extractor=Extract symptoms, history and medications from {in};Summariser=Write a structured clinical summary of {prev};UrgencyScorer=Score clinical urgency from 0 to 1 for {prev};Referral=Draft a referral note for the doctor from {prev} with urgency {score}|Summarise clinical notes, score urgency and draft referrals for doctor review
healthcare.discharge_summary|Discharge summary drafting|record|high|y|pipe|file|Collector=Collect diagnoses, procedures and medications from {in};Writer=Draft a patient-friendly discharge summary from {prev};Checker=Score 0 to 1 how complete and accurate the summary is: {prev};Finaliser=Finalise the discharge summary {prev} noting completeness {score}|Draft discharge summaries for clinician sign-off
healthcare.radiology_qa|Radiology report quality check|report|high|n|pipe||Parser=List the findings and impressions in {in};Consistency=Check whether impressions in {prev} follow from the findings;QualityScorer=Score report quality 0 to 1 from {prev};Feedback=Write feedback for the radiologist on {prev} with quality {score}|Check radiology reports for consistency and completeness
healthcare.appointment_router|Patient appointment router|request|medium|n|router||UrgencyCheck=Score 0 to 1 how urgent this patient request is: {in};UrgentDesk=Arrange a same-day slot and safety advice for: {in};RoutineDesk=Offer the next routine appointment and preparation steps for: {in};ToneCheck=Score 0 to 1 how clear and kind this reply is: {prev}|Route patient requests to urgent or routine booking
healthcare.drug_interaction|Drug interaction review|prescription|high|n|committee|kb|Pharmacologist=Identify drug-drug interactions in {in};Clinician=Assess clinical relevance of interactions in {in};SafetyOfficer=List contraindications and monitoring needs for {in};RiskJudge=Score overall interaction risk 0 to 1 from {items};Advisor=Write prescriber advice from {items} with risk {score}|Multi-expert review of prescription interactions
healthcare.patient_feedback|Patient feedback analysis|feedback|low|n|fan||Splitter=Split {in} into individual patient comments;Analyst=Classify the theme and sentiment of {item} given the batch {in};Satisfaction=Score overall patient satisfaction 0 to 1 from {items};Reporter=Write an improvement report from {items} with satisfaction {score}|Find themes in patient feedback and suggest improvements
# ── pharma ──
pharma.adverse_events|Adverse event case processing|case|high|y|pipe|kb|Intake=Extract patient, drug, event and timing details from {in};Coder=Code the event in {prev} with MedDRA-style terms;Seriousness=Score seriousness 0 to 1 of {prev};Narrative=Write a pharmacovigilance case narrative from {prev} with seriousness {score}|Process adverse event reports into coded case narratives
pharma.trial_matching|Clinical trial matching|patient_profile|high|y|fan|kb|Criteria=List eligibility criteria relevant to {in};Matcher=Check {item} against the profile {in};Eligibility=Score overall trial eligibility 0 to 1 from {items};Summary=Summarise eligibility findings {items} with score {score} for the investigator|Match patient profiles to trial criteria for investigator review
pharma.submission_review|Regulatory submission review|dossier|high|n|fan|file|Sections=List the sections of {in} that need review;Reviewer=Review {item} of the dossier {in} for gaps;Readiness=Score submission readiness 0 to 1 from {items};GapReport=Write a gap report from {items} with readiness {score}|Review regulatory dossiers section by section
pharma.literature_watch|Safety literature surveillance|drug|medium|n|fan|web|Searcher=List recent publications mentioning {in};Reader=Extract any safety signals for {in} from {item};SignalScore=Score strength of new safety signals 0 to 1 from {items};Digest=Write a surveillance digest from {items} with signal strength {score}|Weekly literature watch for drug safety signals
pharma.protocol_deviation|Protocol deviation assessment|deviation|high|n|pipe||Classifier=Classify the protocol deviation in {in};Impact=Assess impact of {prev} on subject safety and data integrity;Severity=Score deviation severity 0 to 1 from {prev};CAPA=Propose corrective and preventive actions for {prev} with severity {score}|Assess trial protocol deviations and propose CAPA
pharma.label_compliance|Product label compliance|label|medium|n|committee|kb|RegulatoryExpert=Check {in} against labelling regulations;MedicalWriter=Check clarity and accuracy of {in};QualityLead=Check {in} for version and artwork consistency;ComplianceJudge=Score label compliance 0 to 1 from {items};Findings=List required label changes from {items} with score {score}|Check product labels against regulations
# ── banking ──
banking.loan_underwriting|Loan underwriting assistant|application|high|y|committee|calc|CreditAnalyst=Assess repayment capacity in {in};RiskAnalyst=Identify credit risks in {in};PolicyChecker=Check {in} against lending policy;CreditCommittee=Score approval likelihood 0 to 1 from {items};Memo=Write a credit decision memo from {items} with score {score}|Committee-style loan assessment with fairness safeguards
banking.kyc_review|KYC document review|customer_file|high|y|pipe|file|DocChecker=List KYC documents present and missing in {in};Verifier=Check consistency of details across {prev};RiskRating=Score customer risk 0 to 1 from {prev};Outcome=Write the KYC review outcome for {prev} with risk {score}|Review KYC files for completeness and risk
banking.aml_alerts|AML alert triage|alerts|high|y|fan|kb|Batcher=Split {in} into individual AML alerts;Investigator=Investigate {item} for suspicious patterns within {in};Priority=Score overall escalation priority 0 to 1 from {items};SAR=Draft a suspicious-activity summary from {items} with priority {score}|Triage AML alerts and draft investigation summaries
banking.complaints|Customer complaint router|complaint|medium|n|router||Severity=Score 0 to 1 how serious and regulatory-sensitive this complaint is: {in};Escalations=Draft an escalation response and remediation plan for: {in};ServiceDesk=Draft a helpful standard response for: {in};ToneCheck=Score 0 to 1 how empathetic and clear this reply is: {prev}|Route complaints by severity and draft responses
banking.credit_memo|Credit memo writer|borrower|medium|y|pipe|calc|Financials=Extract key financial ratios for {in};Analysis=Analyse strengths and weaknesses from {prev};RiskScore=Score credit risk 0 to 1 from {prev};Memo=Write a credit memo from {prev} with risk {score}|Draft credit memos from borrower data
banking.fraud_cases|Card fraud case review|cases|high|y|fan||Splitter=Split {in} into individual fraud cases;Analyst=Assess {item} for fraud indicators given {in};FraudScore=Score overall fraud likelihood 0 to 1 from {items};Report=Write a fraud review report from {items} with likelihood {score}|Review suspected card-fraud cases
# ── insurance ──
insurance.claims_triage|Claims triage|claim|high|y|pipe|kb|Intake=Extract policy, incident and loss details from {in};Coverage=Check coverage for {prev} against policy terms;Complexity=Score claim complexity 0 to 1 from {prev};Routing=Recommend a handling route for {prev} with complexity {score}|Triage new insurance claims and check coverage
insurance.fraud_screening|Claims fraud screening|claim|high|y|committee||PatternAnalyst=Look for known fraud patterns in {in};DocumentExaminer=Check documents in {in} for inconsistencies;Adjuster=Assess plausibility of the loss in {in};FraudPanel=Score fraud likelihood 0 to 1 from {items};Referral=Write an SIU referral note from {items} with likelihood {score}|Panel review of claims for fraud indicators
insurance.policy_compare|Policy comparison|policies|low|n|fan|file|Policies=List the policies described in {in};Analyst=Summarise cover, exclusions and limits of {item};BestFit=Score 0 to 1 how well the best option fits the need in {items};Advice=Write a plain-language comparison from {items} with fit {score}|Compare insurance policies for a customer
insurance.underwriting|Underwriting risk assessment|proposal|high|y|pipe|calc|Profile=Extract risk factors from {in};Assessor=Assess each risk factor in {prev};RiskScore=Score insurable risk 0 to 1 from {prev};Terms=Propose underwriting terms for {prev} with risk {score}|Assess proposals and suggest underwriting terms
insurance.subrogation|Subrogation opportunity finder|claims|medium|n|fan||Splitter=Split {in} into individual closed claims;Reviewer=Identify third-party liability in {item};Recovery=Score overall recovery potential 0 to 1 from {items};Report=List subrogation opportunities from {items} with potential {score}|Find recovery opportunities in closed claims
insurance.query_router|Policyholder query router|query|low|n|router|kb|IsClaim=Score 0 to 1 how likely this query is about a claim: {in};ClaimsDesk=Answer this claims query with next steps: {in};PolicyDesk=Answer this policy or billing query: {in};Clarity=Score 0 to 1 how clear this reply is: {prev}|Route policyholder questions to the right desk
# ── capital markets ──
markets.earnings_call|Earnings call summariser|transcript|low|n|fan|file|Sections=Split {in} into management remarks and Q&A topics;Analyst=Summarise key numbers and guidance in {item};Sentiment=Score management confidence 0 to 1 from {items};Brief=Write an earnings brief from {items} with confidence {score}|Summarise earnings calls into investor briefs
markets.esg_screening|ESG screening|company|medium|n|committee|web|Environmental=Assess environmental performance of {in};Social=Assess social and labour practices of {in};Governance=Assess governance quality of {in};ESGPanel=Score overall ESG quality 0 to 1 from {items};Report=Write an ESG screening note from {items} with score {score}|Three-pillar ESG review of companies
markets.portfolio_risk|Portfolio risk brief|portfolio|high|n|pipe|calc|Exposures=Summarise sector and factor exposures in {in};Stress=Describe stress-scenario impacts on {prev};RiskLevel=Score portfolio risk 0 to 1 from {prev};Brief=Write a risk brief for the investment committee from {prev} with risk {score}|Portfolio risk briefs for investment committees
markets.research_review|Research note review|note|medium|n|committee||Analyst=Check the investment thesis in {in};Compliance=Check {in} for regulatory disclosure issues;Editor=Check clarity and evidence in {in};Reviewers=Score readiness to publish 0 to 1 from {items};Feedback=Write review feedback from {items} with readiness {score}|Pre-publication review of research notes
markets.trade_surveillance|Trade surveillance|trades|high|y|fan||Splitter=Split {in} into trade alerts;Investigator=Assess {item} for market abuse patterns;Concern=Score overall surveillance concern 0 to 1 from {items};Report=Write a surveillance report from {items} with concern {score}|Review trading alerts for market abuse
markets.suitability|Client suitability check|client_profile|high|y|pipe||Profiler=Summarise risk tolerance and goals in {in};Matcher=Assess product suitability for {prev};Suitability=Score suitability 0 to 1 from {prev};Record=Write a suitability record from {prev} with score {score}|Check investment suitability for clients
# ── education ──
education.ai_tutor|AI tutor|topic|low|n|pipe||Explainer=Explain {in} to a first-year student in 6 sentences;Examples=Add two worked examples to {prev};Accuracy=Score 0 to 1 the accuracy of {prev};Lesson=Finalise the lesson {prev} noting accuracy {score}|Explain topics with examples for students
education.question_bank|Exam question bank|syllabus|medium|n|fan||Units=List the units of {in};Setter=Write 5 exam questions at different Bloom's levels for {item};Coverage=Score 0 to 1 how well {items} cover the syllabus;Paper=Assemble a question paper from {items} with coverage {score}|Generate exam questions mapped to syllabus units
education.essay_feedback|Essay feedback|essay|medium|y|committee||ContentExaminer=Assess argument and evidence in {in};LanguageExaminer=Assess language and structure in {in};IntegrityChecker=Check {in} for referencing and integrity issues;Moderator=Score the essay 0 to 1 from {items};Feedback=Write constructive feedback from {items} with score {score}|Moderated essay feedback with integrity checks
education.admissions|Admissions screening|application|high|y|committee||AcademicReviewer=Assess academic record in {in};StatementReviewer=Assess the statement of purpose in {in};PotentialReviewer=Assess potential and achievements in {in};AdmissionsPanel=Score admission recommendation 0 to 1 from {items};Letter=Write a panel summary from {items} with score {score}|Panel-style admissions screening with fairness safeguards
education.outcome_mapping|Course outcome mapping|course|low|n|fan|file|Outcomes=List the course outcomes of {in};Mapper=Map {item} to programme outcomes and Bloom's level;Alignment=Score outcome alignment 0 to 1 from {items};Matrix=Write a CO-PO mapping summary from {items} with alignment {score}|Map course outcomes to programme outcomes for accreditation
education.student_support|Student support router|query|medium|n|router|kb|Wellbeing=Score 0 to 1 how much this student query needs wellbeing support: {in};Counsellor=Draft a caring reply and connect to campus support for: {in};Office=Answer this academic or administrative query: {in};Care=Score 0 to 1 how kind and helpful this reply is: {prev}|Route student queries to support or the academic office
# ── research ──
research.literature_review|Literature review|question|medium|n|fan|web|Searcher=Find 6 key recent papers on {in};Reader=Summarise method, data and findings of {item};Coverage=Score 0 to 1 how well {items} cover the question;Writer=Write a related-work section from {items} with coverage {score}|Literature reviews for research scholars
research.peer_review|Manuscript peer review|manuscript|high|y|fan|file|Criteria=List the review criteria that matter most for {in};Reviewer=Review {item} for the manuscript {in};Editor=Score acceptance likelihood 0 to 1 from {items};Letter=Draft a decision letter from {items} with score {score}|Editorial first-round peer review
research.grant_review|Grant proposal review|proposal|high|y|committee||ScienceReviewer=Assess scientific merit of {in};FeasibilityReviewer=Assess feasibility and budget of {in};ImpactReviewer=Assess societal impact of {in};Panel=Score funding priority 0 to 1 from {items};Summary=Write a panel summary from {items} with priority {score}|Panel review of research grant proposals
research.originality_check|Originality risk check|text|medium|n|pipe||Claims=List the main claims in {in};Overlap=Identify claims in {prev} that need citations;Risk=Score originality risk 0 to 1 from {prev};Advice=Advise the author on {prev} with risk {score}|Spot uncited claims and originality risks
research.thesis_feedback|Thesis chapter feedback|chapter|medium|n|fan||Sections=Split {in} into sections;Supervisor=Give supervisor feedback on {item};Readiness=Score submission readiness 0 to 1 from {items};Plan=Write a revision plan from {items} with readiness {score}|Supervisor-style feedback on thesis chapters
research.ethics_check|Research ethics check|protocol|high|n|pipe||Risks=List risks to participants in {in};Consent=Check consent and data handling in {prev};EthicsScore=Score ethical readiness 0 to 1 from {prev};Recommendation=Write an ethics committee note from {prev} with score {score}|Pre-screen protocols for the ethics committee
# ── government ──
government.grievance_routing|Citizen grievance routing|grievance|medium|n|router|kb|Urgency=Score 0 to 1 how urgent this grievance is: {in};PriorityCell=Assign to the priority cell with an action plan: {in};Department=Route to the right department with a reply: {in};Clarity=Score 0 to 1 how clear this reply is: {prev}|Route citizen grievances to the right department
government.policy_brief|Policy impact brief|policy|medium|n|committee|web|Economist=Assess economic impact of {in};SocialAnalyst=Assess social and equity impact of {in};LegalAnalyst=Assess legal and implementation issues in {in};Panel=Score expected net benefit 0 to 1 from {items};Brief=Write a policy brief from {items} with score {score}|Multi-perspective policy impact briefs
government.tender_evaluation|Tender evaluation|bids|high|n|committee|calc|TechnicalEvaluator=Evaluate technical compliance of {in};FinancialEvaluator=Evaluate prices and value in {in};IntegrityChecker=Check {in} for conflicts of interest and collusion signs;Committee=Score the recommended bid 0 to 1 from {items};Minutes=Write evaluation minutes from {items} with score {score}|Transparent tender evaluation committees
government.welfare_eligibility|Welfare scheme eligibility|application|high|y|pipe|kb|Extractor=Extract household and income details from {in};Rules=Check {prev} against scheme eligibility rules;Eligibility=Score eligibility 0 to 1 from {prev};Notice=Draft an eligibility notice from {prev} with score {score}|Check scheme eligibility for officer approval
government.rti_response|RTI response drafting|request|medium|n|pipe|file|Parser=List the information sought in {in};Locator=Identify records that answer {prev};Exemptions=Score 0 to 1 how much of {prev} can be disclosed;Response=Draft an RTI reply from {prev} with disclosure {score}|Draft Right-to-Information replies
government.public_consultation|Public consultation analysis|submissions|low|n|fan||Splitter=Split {in} into individual submissions;Analyst=Summarise the position and reasons in {item};Support=Score overall public support 0 to 1 from {items};Report=Write a consultation report from {items} with support {score}|Summarise public consultation responses
# ── legal ──
legal.contract_review|Contract clause review|contract|high|n|fan|file|Clauses=List every clause in {in};Analyst=Flag risks and missing protections in {item};Risk=Score overall contract risk 0 to 1 from {items};Summary=Write a contract risk summary from {items} with risk {score}|Clause-by-clause contract risk review
legal.case_research|Case law research|issue|medium|n|fan|web|Questions=Break {in} into legal questions;Researcher=Find relevant precedents for {item};Strength=Score strength of the legal position 0 to 1 from {items};Memo=Write a research memo from {items} with strength {score}|Research precedents for legal issues
legal.compliance_gap|Compliance gap analysis|process|high|n|fan|kb|Obligations=List regulatory obligations relevant to {in};Auditor=Check whether {item} is met by the process {in};Compliance=Score compliance 0 to 1 from {items};Plan=Write a remediation plan from {items} with compliance {score}|Find compliance gaps against regulations
legal.nda_triage|NDA triage|nda|medium|n|pipe|kb|Terms=Extract key terms from {in};Playbook=Compare {prev} with the company playbook;Deviation=Score deviation from playbook 0 to 1 from {prev};Redlines=Suggest redlines for {prev} with deviation {score}|Triage NDAs against the legal playbook
legal.litigation_risk|Litigation risk assessment|dispute|high|n|committee||Counsel=Assess merits of {in};Economist=Estimate exposure and costs in {in};Strategist=Assess settlement options for {in};Panel=Score litigation risk 0 to 1 from {items};Memo=Write a litigation strategy memo from {items} with risk {score}|Assess disputes and settlement options
legal.regulatory_change|Regulatory change impact|regulation|medium|n|pipe|web|Changes=Summarise what changed in {in};Impact=Identify business processes affected by {prev};Urgency=Score implementation urgency 0 to 1 from {prev};Actions=Write an action plan for {prev} with urgency {score}|Track regulatory changes and their impact
# ── hr ──
hr.resume_screening|Resume screening|resume|high|y|committee||SkillsReviewer=Assess skills against the job in {in};ExperienceReviewer=Assess relevant experience in {in};PotentialReviewer=Assess growth potential in {in};HiringPanel=Score shortlist recommendation 0 to 1 from {items};Note=Write a shortlist note from {items} with score {score}|Fair, panel-style resume screening
hr.job_description|Job description writer|role_brief|low|n|pipe||Drafter=Draft a job description from {in};InclusiveEditor=Rewrite {prev} in inclusive, bias-free language;Quality=Score clarity and inclusiveness 0 to 1 of {prev};Final=Finalise the job description {prev} with quality {score}|Write inclusive job descriptions
hr.interview_kit|Interview kit builder|role|low|n|fan||Competencies=List the key competencies for {in};QuestionWriter=Write 3 structured interview questions and a scoring rubric for {item};Coverage=Score kit coverage 0 to 1 from {items};Kit=Assemble an interview kit from {items} with coverage {score}|Structured interview questions and rubrics
hr.employee_router|Employee query router|query|low|n|router|kb|IsSensitive=Score 0 to 1 how sensitive this employee query is: {in};HRPartner=Draft a confidential HR partner reply for: {in};HRDesk=Answer this HR policy query: {in};Helpfulness=Score 0 to 1 how helpful this reply is: {prev}|Route employee questions to the right HR channel
hr.performance_review|Performance review assistant|review_notes|high|y|pipe||Evidence=Organise evidence of achievements in {in};Balance=Check {prev} for balanced, behaviour-based language;Rating=Score performance 0 to 1 from {prev};Draft=Draft a review summary from {prev} with rating {score}|Evidence-based performance review drafts
hr.exit_interviews|Exit interview analysis|interviews|low|n|fan||Splitter=Split {in} into individual exit interviews;Analyst=Find reasons for leaving in {item};Attrition=Score attrition risk for remaining staff 0 to 1 from {items};Report=Write a retention report from {items} with risk {score}|Find attrition drivers in exit interviews
# ── manufacturing ──
manufacturing.quality_inspection|Quality inspection report|inspection|medium|n|pipe|file|Defects=List defects recorded in {in};Classifier=Classify severity and likely cause of {prev};Quality=Score batch quality 0 to 1 from {prev};Disposition=Recommend a batch disposition for {prev} with quality {score}|Classify defects and recommend batch disposition
manufacturing.predictive_maintenance|Predictive maintenance|sensor_summary|medium|n|fan|calc|Assets=List the assets in {in};Engineer=Assess failure risk for {item};Urgency=Score maintenance urgency 0 to 1 from {items};WorkOrders=Draft prioritised work orders from {items} with urgency {score}|Prioritise maintenance from sensor summaries
manufacturing.root_cause|Root cause analysis|incident|high|n|committee||ProcessEngineer=Find process causes of {in};EquipmentEngineer=Find equipment causes of {in};QualityEngineer=Find material and method causes of {in};RCAPanel=Score confidence in the root cause 0 to 1 from {items};Report=Write a 5-Whys RCA report from {items} with confidence {score}|Fishbone-style root cause analysis
manufacturing.sop_compliance|SOP compliance audit|sop|medium|n|fan|kb|Steps=List the steps of {in};Auditor=Check evidence that {item} is followed;Compliance=Score SOP compliance 0 to 1 from {items};Findings=Write audit findings from {items} with compliance {score}|Audit shop-floor compliance with SOPs
manufacturing.supplier_quality|Supplier quality review|supplier_data|medium|n|pipe||Metrics=Summarise defect and delivery metrics in {in};Trends=Identify trends in {prev};Rating=Score supplier quality 0 to 1 from {prev};Scorecard=Write a supplier scorecard from {prev} with rating {score}|Supplier quality scorecards
manufacturing.safety_incident|Safety incident report|incident|high|y|pipe||Facts=Extract who, what, where and when from {in};Hazards=Identify hazards and contributing factors in {prev};Severity=Score severity 0 to 1 from {prev};Actions=Write corrective actions for {prev} with severity {score}|Safety incident investigation reports
# ── supply chain ──
supplychain.demand_forecast|Demand forecast brief|sales_history|medium|n|committee|calc|Statistician=Describe trend and seasonality in {in};MarketAnalyst=Describe market drivers affecting {in};SalesLead=Describe pipeline signals in {in};ForecastPanel=Score forecast confidence 0 to 1 from {items};Brief=Write a demand forecast brief from {items} with confidence {score}|Consensus demand forecast briefs
supplychain.shipment_exceptions|Shipment exception router|exception|medium|n|router||Critical=Score 0 to 1 how critical this shipment exception is: {in};ControlTower=Draft an expedite plan for: {in};Carrier=Draft a carrier follow-up for: {in};Clarity=Score 0 to 1 how actionable this plan is: {prev}|Route shipment exceptions by criticality
supplychain.supplier_risk|Supplier risk monitoring|suppliers|medium|n|fan|web|Splitter=List the suppliers in {in};Analyst=Assess financial, geographic and compliance risk of {item};Risk=Score portfolio supplier risk 0 to 1 from {items};Report=Write a supplier risk report from {items} with risk {score}|Monitor supplier risk across the portfolio
supplychain.route_disruption|Route disruption response|disruption|high|n|pipe||Impact=Identify shipments affected by {in};Options=Propose alternative routes for {prev};Cost=Score cost impact 0 to 1 of {prev};Plan=Write a disruption response plan from {prev} with impact {score}|Respond to transport disruptions
supplychain.inventory_rebalance|Inventory rebalancing|stock_report|low|n|pipe|calc|Imbalances=Find overstock and stockout risks in {in};Transfers=Propose stock transfers for {prev};Benefit=Score benefit 0 to 1 of {prev};Plan=Write a rebalancing plan from {prev} with benefit {score}|Rebalance stock between locations
supplychain.customs_documents|Customs document check|shipment_docs|high|n|fan|file|Documents=List the documents in {in};Checker=Check {item} for errors and missing data;Readiness=Score clearance readiness 0 to 1 from {items};Corrections=List corrections from {items} with readiness {score}|Pre-check customs documents
# ── retail ──
retail.product_description|Product description writer|product|low|n|pipe||Features=List features and benefits of {in};Writer=Write an engaging product description from {prev};Accuracy=Score 0 to 1 the factual accuracy of {prev};Final=Finalise the description {prev} with accuracy {score}|Write accurate product descriptions
retail.review_insights|Customer review insights|reviews|low|n|fan||Splitter=Split {in} into individual reviews;Analyst=Extract product issues and praise from {item};Satisfaction=Score customer satisfaction 0 to 1 from {items};Report=Write a product insights report from {items} with satisfaction {score}|Turn reviews into product insights
retail.return_fraud|Return fraud screening|return_request|medium|y|committee||PatternAnalyst=Check {in} for return-abuse patterns;OrderAnalyst=Check order and delivery history in {in};PolicyChecker=Check {in} against the returns policy;Panel=Score fraud likelihood 0 to 1 from {items};Decision=Recommend an action from {items} with likelihood {score}|Screen returns for abuse with fair review
retail.customer_service|Customer service router|message|low|n|router|kb|IsOrder=Score 0 to 1 how likely this message is about an order: {in};OrderDesk=Resolve this order or delivery issue: {in};HelpDesk=Answer this product or account question: {in};Tone=Score 0 to 1 how friendly and clear this reply is: {prev}|Route customer messages to the right desk
retail.pricing_brief|Pricing recommendation|product_data|medium|n|committee|calc|CostAnalyst=Assess cost and margin in {in};CompetitorAnalyst=Assess competitor prices in {in};DemandAnalyst=Assess price sensitivity in {in};PricingPanel=Score confidence in a price change 0 to 1 from {items};Brief=Write a pricing recommendation from {items} with confidence {score}|Evidence-based pricing recommendations
retail.catalog_quality|Catalogue quality audit|catalog|low|n|fan||Items=List the catalogue entries in {in};Auditor=Check {item} for missing attributes, errors and policy issues;Quality=Score catalogue quality 0 to 1 from {items};Fixes=List fixes from {items} with quality {score}|Audit product catalogue quality
# ── IT ops ──
itops.incident_triage|IT incident triage|incident|high|n|pipe|kb|Classifier=Classify service, impact and urgency of {in};Diagnosis=Suggest likely causes and checks for {prev};Priority=Score incident priority 0 to 1 from {prev};Runbook=Write first-response steps for {prev} with priority {score}|Classify incidents and suggest first response
itops.change_review|Change risk review|change_request|high|n|committee||Architect=Assess technical risk of {in};Operations=Assess operational and rollback risk of {in};Security=Assess security impact of {in};CAB=Score change approval 0 to 1 from {items};Decision=Write the CAB decision from {items} with score {score}|Change advisory board review
itops.log_anomaly|Log anomaly detection|logs|medium|n|fan|file|Windows=Split {in} into time windows;Detector=Find anomalies and error bursts in {item};Severity=Score overall severity 0 to 1 from {items};Report=Write an anomaly report from {items} with severity {score}|Find anomalies in system logs
itops.helpdesk|IT helpdesk router|ticket|low|n|router|kb|IsAccess=Score 0 to 1 how likely this ticket is about access or accounts: {in};AccessDesk=Resolve this access or password issue: {in};ServiceDesk=Resolve this hardware or software issue: {in};Clarity=Score 0 to 1 how clear these steps are: {prev}|Route helpdesk tickets
itops.capacity_planning|Capacity planning|usage_report|medium|n|pipe|calc|Trends=Describe growth trends in {in};Forecast=Forecast capacity needs from {prev};Risk=Score capacity risk 0 to 1 from {prev};Plan=Write a capacity plan from {prev} with risk {score}|Forecast infrastructure capacity
itops.postmortem|Incident postmortem writer|timeline|low|n|fan||Phases=Split {in} into detection, response and recovery phases;Analyst=Find what went well and what to improve in {item};Learning=Score learning value 0 to 1 from {items};Postmortem=Write a blameless postmortem from {items} with score {score}|Blameless incident postmortems
# ── cyber ──
cyber.soc_triage|SOC alert triage|alerts|high|n|fan|kb|Batcher=Split {in} into individual alerts;Analyst=Investigate {item} for indicators of compromise;Severity=Score overall severity 0 to 1 from {items};Incident=Write an incident summary from {items} with severity {score}|Triage security alerts and summarise incidents
cyber.phishing|Phishing email analysis|email|medium|n|pipe||Indicators=List phishing indicators in {in};Assessment=Assess sender, links and intent in {prev};Likelihood=Score phishing likelihood 0 to 1 from {prev};Advice=Write user and SOC advice for {prev} with likelihood {score}|Analyse suspicious emails
cyber.vulnerability_priority|Vulnerability prioritisation|scan_results|high|n|fan||Findings=List the vulnerabilities in {in};Assessor=Assess exploitability and business impact of {item};Risk=Score overall risk 0 to 1 from {items};Plan=Write a prioritised patch plan from {items} with risk {score}|Prioritise vulnerabilities by real risk
cyber.threat_intel|Threat intelligence brief|threat|medium|n|committee|web|Analyst=Describe the threat actor and tactics in {in};Defender=Map {in} to defensive controls;Hunter=Suggest hunting queries for {in};IntelPanel=Score relevance to us 0 to 1 from {items};Brief=Write a threat brief from {items} with relevance {score}|Threat intelligence briefs for defenders
cyber.access_review|Access rights review|access_list|high|n|fan|file|Accounts=List the accounts and roles in {in};Reviewer=Check {item} for excessive or stale access;Risk=Score access risk 0 to 1 from {items};Actions=List revocations from {items} with risk {score}|Periodic least-privilege access reviews
cyber.policy_qa|Security policy Q&A|question|low|n|pipe|kb|Finder=Find policy passages relevant to {in};Answer=Answer the question using {prev};Confidence=Score 0 to 1 how well {prev} is supported by policy;Final=Finalise the answer {prev} with support {score}|Answer staff security-policy questions
# ── energy ──
energy.outage_response|Outage response router|outage_report|high|n|router||Critical=Score 0 to 1 how critical this outage is: {in};Emergency=Draft an emergency crew dispatch plan for: {in};Planned=Draft a scheduled repair plan for: {in};Clarity=Score 0 to 1 how actionable this plan is: {prev}|Route outages to emergency or planned repair
energy.grid_fault|Grid fault analysis|fault_record|high|n|pipe||Events=Order the protection events in {in};Cause=Identify the likely fault cause from {prev};Confidence=Score diagnosis confidence 0 to 1 from {prev};Report=Write a fault report from {prev} with confidence {score}|Analyse grid protection events
energy.meter_anomaly|Meter anomaly detection|meter_data|medium|y|fan|calc|Meters=List the meters in {in};Analyst=Find consumption anomalies for {item};Risk=Score theft or fault likelihood 0 to 1 from {items};Report=Write an inspection list from {items} with risk {score}|Find meter faults and possible theft
energy.renewable_site|Renewable site assessment|site|medium|n|committee|web|ResourceAnalyst=Assess solar and wind resource at {in};GridAnalyst=Assess grid connection for {in};EnvironmentAnalyst=Assess environmental and land issues for {in};Panel=Score site suitability 0 to 1 from {items};Report=Write a site assessment from {items} with suitability {score}|Assess sites for renewable projects
energy.energy_audit|Building energy audit|audit_data|low|n|fan|calc|Systems=List building systems in {in};Auditor=Find savings opportunities in {item};Savings=Score savings potential 0 to 1 from {items};Report=Write an energy audit report from {items} with potential {score}|Find energy savings in buildings
energy.emissions_report|Emissions report|activity_data|medium|n|pipe|calc|Inventory=Organise scope 1, 2 and 3 activity data in {in};Calculator=Estimate emissions from {prev};Quality=Score data quality 0 to 1 of {prev};Report=Write an emissions report from {prev} with quality {score}|Greenhouse-gas emissions reporting
# ── agriculture ──
agriculture.crop_advisory|Crop advisory|crop_and_region|low|n|pipe|web|Advisor=Give weather-aware sowing and care advice for {in};Translator=Translate {prev} into simple Hindi for farmers;Safety=Score 0 to 1 how safe the pesticide guidance in {prev} is;Final=Finalise the advisory {prev} with safety {score}|Crop advice in local languages
agriculture.pest_diagnosis|Pest and disease diagnosis|symptoms|medium|n|committee|kb|Entomologist=Identify likely pests from {in};Pathologist=Identify likely diseases from {in};Agronomist=Identify nutrient or water stress from {in};Panel=Score diagnosis confidence 0 to 1 from {items};Advice=Write treatment advice from {items} with confidence {score}|Diagnose crop problems from symptoms
agriculture.soil_report|Soil report advisor|soil_test|low|n|pipe|calc|Reader=Interpret nutrient levels in {in};Plan=Recommend fertiliser doses from {prev};Confidence=Score recommendation confidence 0 to 1 for {prev};Card=Write a soil health card from {prev} with confidence {score}|Turn soil tests into fertiliser advice
agriculture.market_prices|Market price brief|commodity|low|n|fan|web|Markets=List major markets for {in};Analyst=Summarise price trend in {item};Outlook=Score price outlook 0 to 1 from {items};Brief=Write a selling advice brief from {items} with outlook {score}|Market price trends for farmers
agriculture.farmer_queries|Farmer query router|query|low|n|router|kb|IsUrgent=Score 0 to 1 how urgent this farmer query is: {in};FieldOfficer=Draft a field officer visit plan for: {in};Helpline=Answer this farming question simply: {in};Clarity=Score 0 to 1 how simple and clear this answer is: {prev}|Route farmer queries to field officers or the helpline
agriculture.scheme_eligibility|Farmer scheme eligibility|farmer_profile|high|y|pipe|kb|Extractor=Extract land, crop and income details from {in};Rules=Check {prev} against scheme rules;Eligibility=Score eligibility 0 to 1 from {prev};Notice=Draft an eligibility notice from {prev} with score {score}|Check farmer eligibility for government schemes
# ── media ──
media.campaign_brief|Campaign brief|product_goal|low|n|pipe||Strategist=Define audience and message for {in};Creative=Write three campaign concepts from {prev};Fit=Score brand fit 0 to 1 of {prev};Brief=Write a campaign brief from {prev} with fit {score}|Marketing campaign briefs
media.content_moderation|Content moderation|post|high|n|committee|kb|SafetyReviewer=Check {in} for harmful content;PolicyReviewer=Check {in} against community guidelines;ContextReviewer=Consider context and intent of {in};ModerationPanel=Score removal need 0 to 1 from {items};Decision=Write a moderation decision with reasons from {items} with score {score}|Consistent content moderation decisions
media.brand_sentiment|Brand sentiment monitor|mentions|low|n|fan||Splitter=Split {in} into individual mentions;Analyst=Classify sentiment and topic of {item};Sentiment=Score overall brand sentiment 0 to 1 from {items};Report=Write a sentiment report from {items} with score {score}|Track brand sentiment
media.seo_audit|SEO content audit|pages|low|n|fan|web|Pages=List the pages in {in};Auditor=Check {item} for SEO and readability issues;Health=Score SEO health 0 to 1 from {items};Plan=Write an SEO fix plan from {items} with health {score}|Audit web pages for SEO
media.press_release|Press release writer|announcement|medium|n|pipe||Facts=List the key facts in {in};Writer=Write a press release from {prev};Accuracy=Score factual accuracy 0 to 1 of {prev};Final=Finalise the release {prev} with accuracy {score}|Fact-checked press releases
media.audience_segments|Audience segment brief|customer_data|medium|y|pipe||Segmenter=Describe customer segments in {in};Personas=Write a persona for each segment in {prev};Value=Score segment value 0 to 1 from {prev};Brief=Write a targeting brief from {prev} with value {score}|Audience segments and personas
# ── real estate ──
realestate.lease_abstraction|Lease abstraction|lease|medium|n|fan|file|Clauses=List key clauses in {in};Abstractor=Extract dates, amounts and obligations from {item};Risk=Score lease risk 0 to 1 from {items};Abstract=Write a lease abstract from {items} with risk {score}|Abstract key terms from leases
realestate.site_safety|Construction site safety audit|site_report|high|n|fan||Areas=List work areas in {in};Inspector=Find safety hazards in {item};Risk=Score site safety risk 0 to 1 from {items};Actions=Write corrective actions from {items} with risk {score}|Construction site safety audits
realestate.valuation|Property valuation brief|property|medium|n|committee|calc|MarketAnalyst=Estimate value from comparables for {in};IncomeAnalyst=Estimate value from income for {in};CostAnalyst=Estimate value from replacement cost for {in};Panel=Score valuation confidence 0 to 1 from {items};Report=Write a valuation brief from {items} with confidence {score}|Three-method property valuation briefs
realestate.bid_comparison|Contractor bid comparison|bids|medium|n|committee|calc|CostEstimator=Compare prices in {in};Engineer=Compare technical scope in {in};RiskAnalyst=Compare schedule and risk in {in};Panel=Score the preferred bid 0 to 1 from {items};Recommendation=Write a bid recommendation from {items} with score {score}|Compare contractor bids fairly
realestate.building_code|Building code check|design_summary|high|n|fan|kb|Elements=List design elements in {in};Checker=Check {item} against building code requirements;Compliance=Score code compliance 0 to 1 from {items};Report=Write a compliance report from {items} with compliance {score}|Pre-check designs against building codes
realestate.tenant_queries|Tenant query router|request|low|n|router|kb|IsMaintenance=Score 0 to 1 how likely this is a maintenance request: {in};Maintenance=Create a maintenance work order for: {in};Leasing=Answer this lease or payment question: {in};Clarity=Score 0 to 1 how clear this reply is: {prev}|Route tenant requests
# ── hospitality ──
hospitality.guest_reviews|Guest review insights|reviews|low|n|fan||Splitter=Split {in} into individual reviews;Analyst=Extract service issues and praise from {item};Satisfaction=Score guest satisfaction 0 to 1 from {items};Report=Write a guest experience report from {items} with satisfaction {score}|Turn guest reviews into actions
hospitality.itinerary|Itinerary planner|trip_request|low|n|pipe|web|Planner=Draft a day-by-day itinerary for {in};Logistics=Check travel times and bookings for {prev};Fit=Score fit to the request 0 to 1 of {prev};Final=Finalise the itinerary {prev} with fit {score}|Plan trips day by day
hospitality.booking_router|Booking query router|query|low|n|router|kb|IsChange=Score 0 to 1 how likely this query is a booking change: {in};Reservations=Handle this booking change: {in};Concierge=Answer this guest question: {in};Tone=Score 0 to 1 how warm and clear this reply is: {prev}|Route guest booking questions
hospitality.allergen_check|Menu allergen check|menu|high|n|pipe|kb|Ingredients=List ingredients of each dish in {in};Allergens=Identify the 14 major allergens in {prev};Confidence=Score confidence in allergen labelling 0 to 1 for {prev};Labels=Write allergen labels for {prev} with confidence {score}|Allergen labelling for menus
hospitality.travel_policy|Travel policy check|travel_request|medium|y|pipe|kb|Details=Extract dates, costs and class of travel from {in};Policy=Check {prev} against the travel policy;Compliance=Score policy compliance 0 to 1 of {prev};Decision=Write an approval note for {prev} with compliance {score}|Check business travel against policy
hospitality.loyalty_offers|Loyalty offer designer|guest_segment|low|n|pipe|calc|Insights=Describe preferences of {in};Offers=Design three loyalty offers for {prev};Value=Score expected value 0 to 1 of {prev};Plan=Write an offer plan from {prev} with value {score}|Design loyalty offers by segment
"""

SHAPES = {
    # slots and parameter names per shape
    "pipe": ["A", "B", "S", "R"],
    "fan": ["P", "W", "S", "R"],
    "committee": ["E1", "E2", "E3", "J", "R"],
    "router": ["C", "H", "L", "Q"],
}
TOOLMAP = {"kb": "kb.search", "calc": "calc.eval", "file": "file.read", "web": "web.search"}
RISK = {"high": (0.90, 6000), "medium": (0.80, 4000), "low": (0.70, 3000)}
PEOPLE_FORBID = "gender, caste, religion, nationality"
# where sex or nationality can be clinically or legally relevant, forbid only what never is
SECTOR_FORBID = {"healthcare": "caste, religion", "pharma": "caste, religion"}


def words(name):
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name).capitalize()


def goal_text(g, mapping):
    for k, v in mapping.items():
        g = g.replace("{" + k + "}", "{" + v + "}")
    return g.replace('"', "'")


def build(entry):
    full, title, inp, risk, people, shape, tools, slots, desc = [x.strip() for x in entry.split("|")]
    sector, pid = full.split(".")
    thr, budget = RISK[risk]
    tools = [TOOLMAP[t] for t in tools.split(",") if t]
    names, goals = zip(*[s.split("=", 1) for s in slots.split(";")])
    assert len(names) == len(SHAPES[shape]), (full, len(names))
    gate = f"require human when confidence < {thr:.2f}"
    forbid_list = SECTOR_FORBID.get(sector, PEOPLE_FORBID)
    forbid = f"forbid {forbid_list}" if people == "y" else ""
    decision_pol = "    policy {\n        " + gate + ("\n        " + forbid if forbid else "") + "\n    }\n"
    tool_line = f"    uses  {', '.join(tools)}\n" if tools else ""

    def agent(name, params, ret, goal, extra="", first=False, decision=False):
        ps = ", ".join(f"{n}: {t}" for n, t in params)
        out = f"agent {name}({ps}) -> {ret} {{\n    role  \"{words(name)} specialist, {title.lower()}\"\n    goal  \"{goal}\"\n"
        if first and tools:
            out += tool_line
        if decision:
            out += decision_pol
        return out + extra + "}\n"

    A = []
    if shape == "pipe":
        a, b, s, r = names
        A.append(agent(a, [(inp, "text")], "text", goal_text(goals[0], {"in": inp}), first=True))
        A.append(agent(b, [("draft", "text")], "text", goal_text(goals[1], {"prev": "draft"})))
        A.append(agent(s, [("work", "text")], "score", goal_text(goals[2], {"prev": "work"}), decision=True))
        A.append(agent(r, [("work", "text"), ("level", "score")], "text",
                       goal_text(goals[3], {"prev": "work", "score": "level"})))
        flow = (f"flow main({inp}: text) {{\n    first  = {a}({inp})\n    work   = {b}(first)\n"
                f"    level  = {s}(work)\n    report = {r}(work, level)\n    emit report, level\n}}\n")
    elif shape == "fan":
        p, w, s, r = names
        A.append(agent(p, [(inp, "text")], "list", goal_text(goals[0], {"in": inp}), first=True, extra="    model fast\n"))
        A.append(agent(w, [("part", "text"), (inp, "text")], "text", goal_text(goals[1], {"item": "part", "in": inp})))
        A.append(agent(s, [("findings", "list")], "score", goal_text(goals[2], {"items": "findings"}), decision=True))
        A.append(agent(r, [("findings", "list"), ("level", "score")], "text",
                       goal_text(goals[3], {"items": "findings", "score": "level"})))
        flow = (f"flow main({inp}: text) {{\n    parts    = {p}({inp})\n"
                f"    findings = par for part in parts {{ {w}(part, {inp}) }}\n"
                f"    level    = {s}(findings)\n    report   = {r}(findings, level)\n    emit report, level\n}}\n")
    elif shape == "committee":
        e1, e2, e3, j, r = names
        for i, e in enumerate((e1, e2, e3)):
            A.append(agent(e, [(inp, "text")], "text", goal_text(goals[i], {"in": inp}), first=(i == 0)))
        A.append(agent(j, [("views", "list")], "score", goal_text(goals[3], {"items": "views"}), decision=True))
        A.append(agent(r, [("views", "list"), ("verdict", "score")], "text",
                       goal_text(goals[4], {"items": "views", "score": "verdict"})))
        flow = (f"flow main({inp}: text) {{\n    views   = par {{ {e1}({inp}), {e2}({inp}), {e3}({inp}) }}\n"
                f"    verdict = {j}(views)\n    report  = {r}(views, verdict)\n    emit report, verdict\n}}\n")
    else:  # router
        c, h, l, q = names
        A.append(agent(c, [(inp, "text")], "score", goal_text(goals[0], {"in": inp}), extra="    model fast\n"))
        A.append(agent(h, [(inp, "text")], "text", goal_text(goals[1], {"in": inp}), first=True))
        A.append(agent(l, [(inp, "text")], "text", goal_text(goals[2], {"in": inp}), first=True))
        A.append(agent(q, [("reply", "text")], "score", goal_text(goals[3], {"prev": "reply"}), decision=True))
        flow = (f"flow main({inp}: text) {{\n    if {c}({inp}) >= 0.5 {{\n        reply = {h}({inp})\n    }} else {{\n"
                f"        reply = {l}({inp})\n    }}\n    quality = {q}(reply)\n    if quality < 0.7 {{\n"
                f"        reply = {h}({inp})\n    }}\n    emit reply, quality\n}}\n")

    head = (f"// {SECTORS[sector]} · {title}\n// {desc}\n"
            f"// AlgoLang domain pack {full} · risk: {risk} · generated by tools/make_packs.py\n\n"
            'model smart = "claude-sonnet-5-5"\nmodel fast  = "claude-haiku-5-5"\n')
    head += "".join(f"tool {t}\n" for t in tools)
    head += f"\npolicy {{\n    budget tokens {budget}\n    retry 1\n}}\n\n"
    src = head + "\n".join(A) + "\n" + flow
    meta = dict(id=full, sector=sector, sector_name=SECTORS[sector], title=title, description=desc,
                input=inp, risk=risk, people=people == "y", pattern=shape, tools=tools,
                agents=list(names), human_threshold=thr, budget_tokens=budget,
                forbid=forbid_list.split(", ") if people == "y" else [],
                path=f"packs/{sector}/{pid}.algo")
    return full, src, meta


def main():
    out = ROOT / "packs"
    catalog, errors = [], 0
    lines = [l for l in DOMAINS.strip().splitlines() if l.strip() and not l.startswith("#")]
    for entry in lines:
        full, src, meta = build(entry)
        sector, pid = full.split(".")
        try:
            compile_source(src, f"{pid}.algo", out / sector)
        except Exception as e:  # noqa
            errors += 1
            print(f"✗ {full}: {e}")
            continue
        (out / sector).mkdir(parents=True, exist_ok=True)
        (out / sector / f"{pid}.algo").write_text(src, encoding="utf-8")
        catalog.append(meta)
    (out / "catalog.json").write_text(json.dumps({"version": "0.2.0", "sectors": SECTORS, "packs": catalog},
                                                 indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"✓ wrote {len(catalog)} domain packs in {len({m['sector'] for m in catalog})} sectors → {out}"
          + (f"  ({errors} failed)" if errors else ""))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
